"""
Transform stage: turns a bare 9:16 streamer clip into a *transformative* Short.

Pipeline position:  sources -> processor (9:16) -> [transform] -> poster

Per clip it produces:
  - AI commentary + a varied AI title/description/hashtags
  - a per-clip DECISION on whether to narrate at all — clips where the streamer is
    already talking/reacting are left alone (we don't talk over them); only clips that
    genuinely benefit get a voiceover
  - when narrating: an AI-PICKED neural voice matched to the clip's tone
  - a short on-screen text HOOK + burned captions
  - a "Subscribe & Like" end card (visual CTA, never narrated)
  - an AI-disclosure flag the posters set natively (containsSyntheticMedia / is_aigc)

Everything here runs unattended; nothing requires a human in the loop.
"""
from dataclasses import dataclass, field
from pathlib import Path
import shutil
import tempfile

from ..sources import Clip


@dataclass
class ScriptResult:
    commentary: str          # spoken voiceover text (used only when narrate is True)
    title: str               # platform title / caption headline
    description: str          # longer description (YouTube) — varied per clip
    hashtags: list[str] = field(default_factory=list)   # WITHOUT leading '#'
    voice: str = ""          # AI-picked voice id from the roster ("" if not chosen/invalid)
    narrate: bool = True     # False = clip stands on its own, don't talk over it
    hook: str = ""           # short on-screen text hook (shown even when not narrating)


@dataclass
class Transformed:
    path: Path               # the finished, ready-to-post video
    script: ScriptResult
    ai_label: bool           # disclose as AI-assisted on post
    voice: str = ""          # the voice actually used ("" if the clip wasn't narrated)
    narrated: bool = False


def transform(clip: Clip, processed: Path, out: Path, cfg: dict) -> Transformed:
    """Generate commentary (+ maybe voiceover) + captions + end card and render the Short.

    `processed` is the 9:16 file from the processor stage. `out` is the final file.
    """
    from . import script as _script
    from . import tts as _tts
    from . import compose as _compose
    from . import endcard as _endcard

    tcfg = cfg["transform"]
    vcfg = tcfg["voiceover"]
    ccfg = tcfg["captions"]
    ecfg = tcfg.get("endcard", {})
    backend = vcfg.get("backend", "edge")

    roster = vcfg.get("roster") if (backend == "edge" and vcfg.get("auto_select")) else None
    result = _script.generate(clip, tcfg["llm"], roster=roster)

    # Narrate only if the AI decided it adds value AND voiceover is enabled.
    do_narrate = bool(vcfg["enabled"] and result.narrate and result.commentary.strip())

    used_voice = ""
    narrated = False
    with tempfile.TemporaryDirectory(prefix="vp_transform_") as tmp:
        tmp_dir = Path(tmp)

        voice_audio: Path | None = None
        if do_narrate:
            used_voice = result.voice or vcfg.get("default_voice", "")
            voice_audio = _tts.synthesize(
                result.commentary, tmp_dir / "voice",
                backend=backend, voice=used_voice, rate=vcfg.get("rate", 175),
            )
            narrated = True

        # Hook banner is always shown (the sound-off scroll-stopper); the spoken line is
        # only captioned when we actually narrate.
        hook_text = None
        captions_text = None
        if ccfg["enabled"]:
            hook_text = result.hook or None
            captions_text = result.commentary if narrated else None

        # Render the body, then append the end card (if enabled) for the final file.
        endcard_on = bool(ecfg.get("enabled"))
        body = (tmp_dir / "body.mp4") if endcard_on else out
        _compose.compose(
            video=processed, out=body, voiceover=voice_audio,
            duck_db=vcfg["duck_db"],
            captions_text=captions_text, hook_text=hook_text, font_size=ccfg["font_size"],
        )
        if endcard_on:
            _endcard.append(
                body, out,
                text=ecfg.get("text", "SUBSCRIBE & LIKE"),
                subtext=ecfg.get("subtext", ""),
                duration=float(ecfg.get("duration", 2.0)),
                font_size=int(ecfg.get("font_size", 96)),
                bg=ecfg.get("bg_color", "black"),
            )

    return Transformed(
        path=out, script=result,
        ai_label=bool(tcfg.get("ai_label", True)),
        voice=used_voice, narrated=narrated,
    )
