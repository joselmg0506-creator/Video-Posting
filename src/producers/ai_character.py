"""
AI-character producer — a recurring "creature universe" (not one-off Italian brainrot).

Front-half for content_type=ai_character:
  1. LLM invents an absurd character — OR brings back an existing one for a new episode —
     grounded in a persisted character "bible" so the cast recurs and lore builds (this is
     the serialization that gives people a reason to subscribe). (Anthropic)
  2. Flux generates the character art, consistent across panels (fal.ai / Replicate)
  3. TTS narrates the lore over the top (edge-tts)
  4. Ken-Burns slideshow of the panels (+ optional Content-ID-safe music), captions + hook
  5. loop-back outro

Needs ANTHROPIC_API_KEY + FAL_KEY (or REPLICATE_API_TOKEN) + internet + ffmpeg.
"""
import hashlib
import json
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
IMG_STYLE = ("hyperdetailed 3D render, surreal absurdist meme creature, dramatic studio "
             "lighting, vivid colors, vertical 9:16 composition, centered subject")


# ───────────────────────────────── character bible ────────────────────────────────────

def _load_bible(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _append_bible(path: str, entry: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    cast = _load_bible(path)
    if not any(c.get("name", "").lower() == entry["name"].lower() for c in cast):
        cast.append(entry)
        p.write_text(json.dumps(cast, indent=2), encoding="utf-8")


# ───────────────────────────────── invention (LLM) ────────────────────────────────────

def _system(panels: int, target_words: int, cast: list[dict], returning: dict | None) -> str:
    s = f"""You write episodes for a recurring cast of absurd surreal meme creatures (a
single shared "brainrot" universe). Each creature is a mashup (often animal + object) with a
silly mock-Italian-ish name, ridiculous lore, and a catchphrase. The cast RECURS — building
running jokes, rivalries, and a world people follow.

Return ONLY a JSON object with keys:
- "name": the character's name (for a returning character, use its EXACT existing name).
- "image_prompts": an array of EXACTLY {panels} prompts for an image generator describing the
  SAME creature consistently (same body, colors, features) in different poses/scenes. One
  vivid sentence each; do not include the name.
- "narration": an over-the-top hype spoken script of about {target_words} words — announce the
  name, its lore/powers (or this episode's new escapade), and end on the catchphrase. Spoken
  sentences for TTS; no emojis/hashtags/stage-directions.
- "title": a YouTube-Shorts title, <= 80 chars, hooky, NO '#'.
- "description": 1-2 sentences.
- "hashtags": 3-6 lowercase tags, no '#'.
- "hook": a 3-6 word ALL-CAPS-friendly on-screen banner."""

    if cast:
        roster = "\n".join(f"  - {c['name']}: {c.get('blurb', '')}" for c in cast[-14:])
        s += f"\n\nExisting cast in this universe (you may reference/feud with them in lore):\n{roster}"
    if returning:
        s += (f"\n\nThis is a NEW EPISODE of the EXISTING character "
              f"'{returning['name']}' ({returning.get('blurb', '')}). Keep the same creature "
              f"(same name and look — describe it consistently) but put it in a FRESH scenario "
              f"with new lore. Do NOT invent a new name.")
    else:
        s += ("\n\nInvent a BRAND-NEW creature that fits this universe (do not reuse an existing "
              "name, and do not copy real existing memes like 'Tralalero Tralala').")
    return s


def _invent(llm_cfg: dict, panels: int, target_words: int, seed: int,
            cast: list[dict], returning: dict | None) -> dict:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the ai_character channel.")
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    prompt = (f"Write episode #{seed}. " +
              ("Bring the returning character back with a new twist." if returning
               else "Invent something weird and unlike the existing cast."))
    msg = client.messages.create(
        model=llm_cfg["model"],
        max_tokens=1200,
        temperature=1.0,
        system=[{"type": "text", "text": _system(panels, target_words, cast, returning),
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)
    data["hashtags"] = [h.lstrip("#").strip() for h in data.get("hashtags", []) if h.strip()][:6]
    prompts = [str(p).strip() for p in data.get("image_prompts", []) if str(p).strip()]
    if not prompts:
        raise RuntimeError("LLM returned no image_prompts")
    data["image_prompts"] = prompts[:panels]
    return data


# ───────────────────────────────── rendering ─────────────────────────────────────────

def _render_one(spec: dict, item_id: str, channel: dict, cfg: dict,
                images: list[Path] | None = None) -> "object":
    """Render a finished Short from a `spec`. `images` may be injected for testing;
    otherwise generated via the configured provider."""
    cc = channel["ai_character"]
    tcfg = cfg.get("transform", {})
    ccfg = tcfg.get("captions", {})
    ecfg = tcfg.get("endcard", {})
    voice = cc.get("voice") or "en-US-GuyNeural"
    narration = (spec.get("narration") or "").strip()
    if not narration:
        raise RuntimeError("empty narration")

    final = Path(cfg["paths"]["processed"]) / f"{item_id.replace(':', '_')}_final.mp4"

    with tempfile.TemporaryDirectory(prefix="vp_char_") as tmp:
        tmp_dir = Path(tmp)
        if images is None:
            prompts = [f"{p}, {IMG_STYLE}" for p in spec["image_prompts"]]
            images = visuals.gen_images(cc.get("image_provider", "fal"),
                                        cc.get("image_model", "fal-ai/flux/schnell"),
                                        prompts, tmp_dir)
        audio, words = _tts.synthesize(narration, tmp_dir / "vo", backend="edge",
                                       voice=voice, return_timings=True)
        adur = _probe_duration(audio) or (len(narration.split()) / WPM * 60)
        bg = visuals.make_slideshow(images, adur + 0.4, tmp_dir / "bg.mp4", tmp_dir,
                                    music_dir=cc.get("music_dir"))

        endcard_on = bool(ecfg.get("enabled"))
        body = (tmp_dir / "body.mp4") if endcard_on else final
        _compose.compose(
            video=bg, out=body, voiceover=audio,
            caption_words=words or None,
            captions_text=None if words else narration,
            hook_text=(spec.get("hook") or None) if ccfg.get("enabled", True) else None,
            font_size=ccfg.get("font_size", 72),
            hook_duration=float(ccfg.get("hook_seconds", 2.5)),
        )
        if endcard_on:
            _endcard.append(body, final, cta_text=ecfg.get("cta_text", ""),
                            loop_seconds=float(ecfg.get("loop_seconds", 0.5)),
                            cta_font=int(ecfg.get("cta_font_size", 46)))

    from main import PostItem
    return PostItem(
        item_id=item_id, path=final,
        title=spec.get("title", spec.get("name", "AI character"))[:100],
        description=spec.get("description", ""),
        hashtags=spec.get("hashtags", []),
        ai_label=bool(tcfg.get("ai_label", True)),
        voice=voice, source="ai", creator=spec.get("name", ""),
    )


def produce(channel: dict, cfg: dict, state, cap: int) -> list:
    cc = channel.get("ai_character", {})
    panels = int(cc.get("panels", 3))
    target_words = max(40, int(cc.get("target_seconds", 30) / 60 * WPM))
    recurring_rate = float(cc.get("recurring_rate", 0.4))
    bible_path = cc.get("bible", "./data/character_bible.json")
    lcfg = cfg["transform"]["llm"]

    items: list = []
    attempts = 0
    while len(items) < cap and attempts < cap * 3:
        attempts += 1
        try:
            cast = _load_bible(bible_path)
            returning = random.choice(cast) if (cast and random.random() < recurring_rate) else None
            spec = _invent(lcfg, panels, target_words,
                           seed=random.randint(1, 10_000_000), cast=cast, returning=returning)
            item_id = "char:" + hashlib.sha1(
                (spec["name"] + spec.get("narration", "")).encode()).hexdigest()[:12]
            if state.is_posted(item_id) or state.is_pending(item_id):
                continue
            kind = f"returning {spec['name']!r}" if returning else f"new {spec['name']!r}"
            print(f"    generating character ({kind}, {panels} panels)")
            items.append(_render_one(spec, item_id, channel, cfg))
            if not returning:   # remember new characters so they can recur later
                _append_bible(bible_path, {"name": spec["name"],
                                           "blurb": (spec.get("description", "")[:140])})
        except Exception as e:
            print(f"    [character] generation failed: {e}")
    return items
