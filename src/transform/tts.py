"""
Text-to-speech with selectable backends:

- "edge"   : Microsoft's online NEURAL voices via edge-tts. Natural, FREE, gives word-level
             timings (used for karaoke captions). Outputs mp3. (default)
- "kokoro" : Kokoro-82M local neural TTS via kokoro-onnx (Apache-2.0, CPU, no GPU/PyTorch).
             More natural/expressive than edge for storytelling. `pip install kokoro-onnx`;
             the model (~310MB) auto-downloads once to data/models/. NO word timings, so
             captions must be aligned with faster-whisper. Outputs wav.
- "offline": pyttsx3 (Windows SAPI5 / espeak). Robotic, no internet. Outputs wav.

`synthesize` returns the actual file it wrote (extension depends on the backend).
"""
from pathlib import Path

# Kokoro model files (downloaded on first use). en voices: af_heart/af_sarah/am_adam/bm_george…
# it voices start with 'i' (if_sara/im_nicola). See the kokoro-onnx voice list.
_KOKORO_FILES = {
    "model": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
              Path("data/models/kokoro-v1.0.onnx")),
    "voices": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
               Path("data/models/voices-v1.0.bin")),
}
_KOKORO_OBJ = None


def synthesize(
    text: str,
    out_path: Path,
    *,
    backend: str = "edge",
    voice: str = "en-US-AndrewNeural",
    rate: int = 175,
    return_timings: bool = False,
):
    """Synthesize speech. Returns the audio Path, or (Path, word_timings) when
    return_timings is True — word_timings is a list of (word, start, end) seconds
    (empty for the offline backend, which has no word boundaries)."""
    out_path = Path(out_path)
    if backend == "edge":
        return _edge(text, out_path.with_suffix(".mp3"), voice, return_timings)
    if backend == "kokoro":
        p = _kokoro(text, out_path.with_suffix(".wav"), voice)
        return (p, []) if return_timings else p   # no word timings — align captions via whisper
    if backend == "offline":
        p = _offline(text, out_path.with_suffix(".wav"), rate, voice)
        return (p, []) if return_timings else p
    raise ValueError(f"Unknown voiceover backend: {backend!r} (use 'edge', 'kokoro', or 'offline')")


def _kokoro(text: str, out_path: Path, voice: str) -> Path:
    import urllib.request
    import soundfile as sf
    from kokoro_onnx import Kokoro
    global _KOKORO_OBJ
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if _KOKORO_OBJ is None:
        paths = []
        for url, p in _KOKORO_FILES.values():
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                print(f"    [kokoro] downloading {p.name} (one-time)…")
                urllib.request.urlretrieve(url, p)
            paths.append(str(p))
        _KOKORO_OBJ = Kokoro(paths[0], paths[1])
    v = voice or "af_heart"
    lang = "it" if v[:1].lower() == "i" else "en-us"
    samples, sr = _KOKORO_OBJ.create(text, voice=v, speed=1.0, lang=lang)
    sf.write(str(out_path), samples, sr)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("Kokoro produced no audio")
    return out_path


def _edge(text: str, out_path: Path, voice: str, want_timings: bool = False):
    import asyncio
    import edge_tts

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not voice:
        voice = "en-US-AndrewNeural"

    words: list[tuple[str, float, float]] = []

    async def _run() -> None:
        # boundary="WordBoundary" makes the service emit per-word timing metadata.
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
        with open(out_path, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7        # 100ns units -> seconds
                    words.append((chunk["text"], start, start + chunk["duration"] / 1e7))

    # Private selector loop: avoids the deprecated global policy and Windows Proactor noise.
    loop = asyncio.SelectorEventLoop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            f"edge-tts produced no audio for voice {voice!r}. "
            "Check the internet connection and that the voice id is valid."
        )
    return (out_path, words) if want_timings else out_path


def _offline(text: str, out_path: Path, rate: int, voice_substr: str) -> Path:
    import pyttsx3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)

    # The roster uses edge voice ids (e.g. "en-US-AndrewNeural") which won't match a SAPI
    # voice name — in that case we just fall through to the system default voice.
    if voice_substr:
        needle = voice_substr.lower()
        for v in engine.getProperty("voices"):
            if needle in (getattr(v, "name", "") or "").lower():
                engine.setProperty("voice", v.id)
                break

    engine.save_to_file(text, str(out_path))
    engine.runAndWait()
    engine.stop()

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            "Offline TTS produced no audio. On Windows this needs SAPI5 voices "
            "(built in); on Linux install espeak/espeak-ng."
        )
    return out_path
