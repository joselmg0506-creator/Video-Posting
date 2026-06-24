"""
Transform stage: turns a bare 9:16 clip into a finished, on-style Short.

Pipeline position:  sources -> processor (9:16) -> [transform] -> poster

To make titles/labels actually match the moment, the AI WATCHES the clip (a few frames,
vision) and READS what was said (Whisper transcript), then writes:
  - a narrate-or-NOT decision (don't talk over clips that carry themselves)
  - a varied title / description / hashtags
  - a hook banner + a few editorial "action labels" (the *HE LOST IT* AMP-clip style)
When narrating, it also writes commentary spoken by an AI-picked neural voice.

Captions/labels are centered, bold, colored; clips are crop-to-fill; a loop-back outro
keeps the rewatch loop. Everything runs unattended.
"""
import base64
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..sources import Clip
from ..processor.video import _duration


class ClipRejected(Exception):
    """Raised when the quality gate decides a clip isn't worth posting, so the caller can
    skip it cleanly (and BEFORE the expensive render) instead of treating it as a failure."""


@dataclass
class ScriptResult:
    commentary: str          # spoken voiceover text (used only when narrate is True)
    title: str               # platform title / caption headline
    description: str
    hashtags: list[str] = field(default_factory=list)   # WITHOUT leading '#'
    voice: str = ""          # AI-picked voice id ("" if not chosen/invalid)
    narrate: bool = True
    hook: str = ""           # opening banner line
    labels: list[str] = field(default_factory=list)     # editorial on-screen hype labels
    quality: int = 10        # 1-10 standalone-Short quality (drives the optional quality gate)


@dataclass
class Transformed:
    path: Path
    script: ScriptResult
    ai_label: bool
    voice: str = ""
    narrated: bool = False


def _extract_frames(video: Path, n: int = 4) -> list[str]:
    """Return up to n evenly-spaced frames as base64 JPEGs (for the vision model)."""
    dur = _duration(video) or 0
    if dur <= 0:
        return []
    with tempfile.TemporaryDirectory(prefix="vp_frames_") as td:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video),
             "-vf", f"fps={n}/{dur:.2f},scale=512:-1", "-frames:v", str(n),
             str(Path(td) / "f_%02d.jpg")],
            capture_output=True,
        )
        return [base64.b64encode(f.read_bytes()).decode()
                for f in sorted(Path(td).glob("f_*.jpg"))[:n]]


def transform(clip: Clip, processed: Path, out: Path, cfg: dict) -> Transformed:
    from . import script as _script
    from . import tts as _tts
    from . import compose as _compose
    from . import endcard as _endcard

    tcfg = cfg["transform"]
    vcfg = tcfg["voiceover"]
    ccfg = tcfg["captions"]
    ecfg = tcfg.get("endcard", {})
    lcfg = tcfg["llm"]
    backend = vcfg.get("backend", "edge")

    # --- understand the clip: transcript (what was said) + frames (what's shown) ---
    transcript = ""
    acfg = ccfg.get("asr", {})
    if acfg.get("enabled"):
        try:
            from . import transcribe as _transcribe
            words = _transcribe.transcribe(processed, model=acfg.get("model", "base"),
                                           language=acfg.get("language", "en"))
            transcript = " ".join(w[0] for w in words)
        except Exception as e:
            print(f"    [understand] transcript skipped: {e}")
    frames = _extract_frames(processed, int(lcfg.get("vision_frames", 4))) if lcfg.get("use_vision", True) else []

    roster = vcfg.get("roster") if (backend == "edge" and vcfg.get("auto_select")) else None
    result = _script.generate(clip, lcfg, roster=roster, transcript=transcript, frames=frames)

    # Quality gate (opt-in via transform.quality_min). The score is always logged so you can
    # calibrate a threshold from real runs; rejection happens BEFORE the expensive render.
    quality_min = int(tcfg.get("quality_min", 0) or 0)
    print(f"    quality: {result.quality}/10 (gate: {quality_min or 'off'})")
    if quality_min and result.quality < quality_min:
        raise ClipRejected(f"quality {result.quality} < {quality_min}: {result.title!r}")

    do_narrate = bool(vcfg["enabled"] and result.narrate and result.commentary.strip())
    used_voice, narrated = "", False

    with tempfile.TemporaryDirectory(prefix="vp_transform_") as tmp:
        tmp_dir = Path(tmp)

        voice_audio: Path | None = None
        caption_words = None
        if do_narrate:
            used_voice = result.voice or vcfg.get("default_voice", "")
            voice_audio, caption_words = _tts.synthesize(
                result.commentary, tmp_dir / "voice",
                backend=backend, voice=used_voice, rate=vcfg.get("rate", 175),
                return_timings=True,
            )
            narrated = True

        # Hook banner always; when narrating caption the commentary, else show the
        # editorial hype labels (the AMP-clip look).
        hook_text = (result.hook or None) if ccfg["enabled"] else None
        show_labels = bool(ccfg.get("labels", True))   # mid-screen editorial hype-labels
        labels = (result.labels or None) if (show_labels and ccfg["enabled"] and not narrated) else None
        if narrated and not caption_words:
            caption_words = None

        endcard_on = bool(ecfg.get("enabled"))
        body = (tmp_dir / "body.mp4") if endcard_on else out
        _compose.compose(
            video=processed, out=body, voiceover=voice_audio,
            duck_db=vcfg["duck_db"],
            caption_words=caption_words, labels=labels, hook_text=hook_text,
            font_size=ccfg["font_size"], hook_duration=float(ccfg.get("hook_seconds", 3.0)),
        )
        if endcard_on:
            _endcard.append(
                body, out,
                cta_text=ecfg.get("cta_text", ""),
                loop_seconds=float(ecfg.get("loop_seconds", 0.5)),
                cta_font=int(ecfg.get("cta_font_size", 46)),
            )

    return Transformed(path=out, script=result, ai_label=bool(tcfg.get("ai_label", True)),
                       voice=used_voice, narrated=narrated)
