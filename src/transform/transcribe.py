"""
Local speech-to-text (word-level) via faster-whisper — used to caption the STREAMER's
own audio on clips we don't narrate (the majority). Free, no API key; the model downloads
once on first use and runs on CPU.

Returns a list of (word, start, end) tuples in seconds, suitable for karaoke captions.
"""
from pathlib import Path

_MODELS: dict[str, object] = {}


def _model(size: str):
    if size not in _MODELS:
        from faster_whisper import WhisperModel
        # int8 on CPU keeps it fast enough for short clips without a GPU.
        _MODELS[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODELS[size]


def transcribe(audio: Path, model: str = "base", language: str = "en") -> list[tuple[str, float, float]]:
    """Word-level transcription of a media file's speech. Returns [] on no speech."""
    segments, _info = _model(model).transcribe(
        str(audio),
        language=language,
        word_timestamps=True,
        vad_filter=True,          # skip non-speech (gameplay noise/music) to cut hallucinations
    )
    words: list[tuple[str, float, float]] = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if text and w.end > w.start:
                words.append((text, float(w.start), float(w.end)))
    return words
