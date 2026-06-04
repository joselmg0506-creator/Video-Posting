"""
Text-to-speech with two selectable backends:

- "edge"   : Microsoft's online NEURAL voices via edge-tts. Natural sounding, FREE,
             no API key — only needs an internet connection (already required for the
             AI commentary). Outputs mp3.
- "offline": pyttsx3 (Windows SAPI5 / espeak). Robotic, but works with no internet.
             Outputs wav.

`synthesize` returns the actual file it wrote (extension depends on the backend).
"""
from pathlib import Path


def synthesize(
    text: str,
    out_path: Path,
    *,
    backend: str = "edge",
    voice: str = "en-US-AndrewNeural",
    rate: int = 175,
) -> Path:
    out_path = Path(out_path)
    if backend == "edge":
        return _edge(text, out_path.with_suffix(".mp3"), voice)
    if backend == "offline":
        return _offline(text, out_path.with_suffix(".wav"), rate, voice)
    raise ValueError(f"Unknown voiceover backend: {backend!r} (use 'edge' or 'offline')")


def _edge(text: str, out_path: Path, voice: str) -> Path:
    import asyncio
    import edge_tts

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not voice:
        voice = "en-US-AndrewNeural"

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(out_path))

    # Use a private selector loop: avoids the deprecated global policy and the Windows
    # ProactorEventLoop shutdown noise, without disturbing any caller's loop.
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
    return out_path


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
