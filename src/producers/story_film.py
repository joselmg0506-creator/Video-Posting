"""
Story-film producer — original AI stories told like a short animated MOVIE.

Front-half for content_type=story_film:
  1. One LLM call acts as screenwriter + director: invents an original self-contained story,
     a small CAST with LOCKED visual descriptions, a narrator script, and an ordered list of
     scenes (each with a camera shot + which characters are present). (Anthropic)
  2. Character consistency by construction: each character's exact appearance string is
     injected into EVERY scene image prompt they appear in, so they look the same throughout.
  3. Flux renders each scene in the configured film style (default Pixar-like 3D). (fal/Replicate)
  4. TTS narrates it like a movie (edge-tts) over a cinematic Ken-Burns slideshow of the scenes,
     with karaoke captions + a hook banner and an optional music bed.
  5. loop-back outro.

Fully original (no reused-content / licensing exposure). Needs ANTHROPIC_API_KEY + FAL_KEY
(or REPLICATE_API_TOKEN) + internet + ffmpeg.
"""
import hashlib
import random
import tempfile
from pathlib import Path

from ..config import env
from ..transform import tts as _tts
from ..transform import compose as _compose
from ..transform import endcard as _endcard
from ..transform.compose import _probe_duration
from ..transform.script import _extract_json
from . import visuals

WPM = 150

# Film-style suffixes appended to every scene prompt so the whole video shares one look.
STYLES = {
    "3d_animated": ("Pixar-style 3D animated movie still, cinematic lighting, volumetric light, "
                    "highly detailed, shallow depth of field, vibrant color grade"),
    "anime": ("anime film still, cel-shaded 2D animation, detailed background art, dramatic "
              "lighting, Makoto Shinkai style"),
    "cinematic_realistic": ("photorealistic cinematic film still, 35mm, shallow depth of field, "
                            "dramatic film lighting, color graded, highly detailed"),
    "storybook": ("painterly storybook illustration, soft textured brushwork, warm lighting, "
                  "cinematic children's-film style"),
}
_NEGATIVE = "no text, no watermark, no subtitles, no captions, no letters"


def _system(style_name: str, target_words: int, scenes: int) -> str:
    return f"""You are a screenwriter and director for a faceless YouTube Shorts channel that
posts short ORIGINAL animated story films (~{target_words} words of narration). Visual style
for EVERY shot: {style_name}.

Write one complete, self-contained micro-film: a grabbing hook, rising tension, and a
satisfying twist or emotional payoff. Then storyboard it.

Return ONLY a JSON object with keys:
- "title": <= 80 chars, hooky, NO '#'.
- "description": 1-2 sentences.
- "hashtags": 3-6 lowercase tags, no '#'.
- "hook": a 3-6 word ALL-CAPS-friendly on-screen banner.
- "characters": an array of 1-3 objects {{"name", "appearance"}}. "appearance" is a DETAILED,
  FIXED visual description (age, build, hair, skin, clothing with colors, distinguishing
  features) in the {style_name} style. This EXACT text is reused in every scene the character
  appears in, so describe them precisely and unchangingly — this is what keeps them looking
  the same across the film.
- "narration": the spoken voiceover that tells the story (~{target_words} words), a cinematic
  narrator's voice. Natural spoken sentences for TTS; no emojis, hashtags, or stage directions;
  end on the twist or a line that invites a comment.
- "scenes": an array of EXACTLY {scenes} scene objects IN ORDER, each
  {{"shot", "description", "present"}}:
    - "shot": camera framing — one of: "wide establishing shot", "medium shot", "close-up",
      "over-the-shoulder shot", "low angle shot", "wide shot".
    - "description": what is VISIBLE in this beat (setting, action, mood) — visual only, no
      dialogue or on-screen text.
    - "present": array of character names visible here (a subset of "characters"; [] if none).
  The scenes must depict the narration's story visually, in order, and vary the shots for a
  cinematic feel."""


def _write_film(llm_cfg: dict, theme: str, style_name: str,
                target_words: int, scenes: int) -> dict:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the story_film channel.")
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=llm_cfg["model"],
        max_tokens=2000,
        temperature=1.0,   # variety so every film is different
        system=[{"type": "text", "text": _system(style_name, target_words, scenes),
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   f"Write a fresh, surprising original story film on the theme: {theme}. "
                   "Make it specific and vivid, not generic."}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)
    data["hashtags"] = [h.lstrip("#").strip() for h in data.get("hashtags", []) if h.strip()][:6]
    if not data.get("narration", "").strip():
        raise RuntimeError("LLM returned empty narration")
    if not data.get("scenes"):
        raise RuntimeError("LLM returned no scenes")
    return data


def _scene_prompts(film: dict, style_suffix: str) -> list[str]:
    """Build one image prompt per scene, injecting each present character's LOCKED appearance
    string so characters stay visually consistent across the whole film."""
    cast = {c["name"]: c.get("appearance", "")
            for c in film.get("characters", []) if c.get("name")}
    prompts: list[str] = []
    for sc in film["scenes"]:
        present = [cast[n] for n in sc.get("present", []) if n in cast]
        parts = [style_suffix, sc.get("shot", ""), sc.get("description", "")]
        if present:
            parts.append("featuring " + "; ".join(present))
        parts.append(_NEGATIVE)
        prompts.append(", ".join(p for p in parts if p))
    return prompts


def _render_one(film: dict, item_id: str, channel: dict, cfg: dict,
                images: list[Path] | None = None) -> "object":
    fc = channel["story_film"]
    tcfg = cfg.get("transform", {})
    ccfg = tcfg.get("captions", {})
    ecfg = tcfg.get("endcard", {})
    style_suffix = STYLES.get(fc.get("style", "3d_animated"), STYLES["3d_animated"])
    voice = fc.get("voice") or "en-US-AndrewNeural"
    narration = film["narration"].strip()
    final = Path(cfg["paths"]["processed"]) / f"{item_id.replace(':', '_')}_final.mp4"

    with tempfile.TemporaryDirectory(prefix="vp_film_") as tmp:
        tmp_dir = Path(tmp)
        audio, words = _tts.synthesize(narration, tmp_dir / "vo", backend="edge",
                                       voice=voice, return_timings=True)
        adur = _probe_duration(audio) or (len(narration.split()) / WPM * 60)

        if images is None:
            prompts = _scene_prompts(film, style_suffix)
            images = visuals.gen_images(fc.get("image_provider", "fal"),
                                        fc.get("image_model", "fal-ai/flux/schnell"),
                                        prompts, tmp_dir)
        bg = visuals.make_slideshow(images, adur + 0.4, tmp_dir / "bg.mp4", tmp_dir,
                                    music_dir=fc.get("music_dir"))

        endcard_on = bool(ecfg.get("enabled"))
        body = (tmp_dir / "body.mp4") if endcard_on else final
        _compose.compose(
            video=bg, out=body, voiceover=audio,
            caption_words=words or None,
            captions_text=None if words else narration,
            hook_text=(film.get("hook") or None) if ccfg.get("enabled", True) else None,
            font_size=ccfg.get("font_size", 72),
            hook_duration=float(ccfg.get("hook_seconds", 2.5)),
        )
        if endcard_on:
            _endcard.append(body, final, cta_text=ecfg.get("cta_text", ""),
                            loop_seconds=float(ecfg.get("loop_seconds", 0.5)),
                            cta_font=int(ecfg.get("cta_font_size", 46)))

    from main import PostItem
    cast_names = ", ".join(c.get("name", "") for c in film.get("characters", []))
    return PostItem(
        item_id=item_id, path=final, title=film.get("title", "")[:100],
        description=film.get("description", ""), hashtags=film.get("hashtags", []),
        ai_label=bool(tcfg.get("ai_label", True)), voice=voice,
        source="ai_film", creator=cast_names,
    )


def produce(channel: dict, cfg: dict, state, cap: int) -> list:
    fc = channel.get("story_film", {})
    style_name = STYLES.get(fc.get("style", "3d_animated"), STYLES["3d_animated"])
    scenes = int(fc.get("scenes", 6))
    target_words = max(50, int(fc.get("target_seconds", 55) / 60 * WPM))
    themes = list(fc.get("themes") or ["an unexpected twist"])
    lcfg = cfg["transform"]["llm"]

    items: list = []
    attempts = 0
    while len(items) < cap and attempts < cap * 3:
        attempts += 1
        theme = random.choice(themes)
        try:
            film = _write_film(lcfg, theme, style_name, target_words, scenes)
            item_id = "film:" + hashlib.sha1(film["narration"].encode()).hexdigest()[:12]
            if state.is_posted(item_id) or state.is_pending(item_id):
                continue
            cast = ", ".join(c.get("name", "?") for c in film.get("characters", []))
            print(f"    directing film (theme: {theme!r}; cast: {cast}; {scenes} scenes)")
            items.append(_render_one(film, item_id, channel, cfg))
        except Exception as e:
            print(f"    [film] generation failed: {e}")
    return items
