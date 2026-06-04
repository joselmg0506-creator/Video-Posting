"""
AI commentary + metadata (+ voice pick) via the Anthropic Messages API.

The whole point of this stage is to add ORIGINAL, per-clip value — so the prompt forces
genuinely-varied output specific to this exact clip, no reusable template phrasing. When
a voice roster is supplied, the model ALSO picks the voice whose style best fits the
clip's tone, which adds another axis of per-video variety.

Needs ANTHROPIC_API_KEY (the offline TTS needs no key; the *writing* does).
Prompt caching is applied to the static instruction block so a whole run reuses it.
"""
import json
import re

from ..config import env
from ..sources import Clip
from . import ScriptResult


def _system(persona: str, max_words: int, roster: list[dict] | None) -> str:
    s = f"""You are {persona}.

You write the metadata (and sometimes spoken commentary) for a vertical short-form video
(YouTube Shorts / TikTok) built around ONE clip of a live streamer or gamer.

Your job is to add ORIGINAL value WITHOUT ruining the clip. Hard rules:
- First decide "narrate": should a voiceover be added at all? Set narrate to FALSE when
  the clip already carries itself — the streamer/creator is talking, reacting, or the
  gameplay+audio speaks for itself — because narrating OVER them ruins the moment. Set it
  to TRUE only when a voiceover genuinely adds context or hype to an otherwise quiet or
  confusing clip. When unsure, prefer FALSE.
- "hook": a very short on-screen TEXT hook (<= 7 words), a curiosity-gap or bold claim
  ("Why this 1v4 broke R6"), shown as the opening banner whether or not we narrate. This
  is the sound-off scroll-stopper — make it impossible to scroll past.
- "commentary": the spoken voiceover text, used ONLY if narrate is true. Make it SPECIFIC
  to this exact clip (react to what's happening, name the streamer), never a template,
  varied every time. Spoken plain sentences — no emojis, hashtags, or markdown. At or
  under {max_words} words. If narrate is false, set commentary to "".
- Do NOT claim the clip is yours and do NOT fabricate facts about the streamer.

Return ONLY a JSON object, no prose around it, with these keys:
- "narrate": true or false (see rule above)
- "hook": the short on-screen text hook
- "commentary": the spoken voiceover text (or "" if narrate is false)
- "title": a punchy title/caption headline, 80 characters or fewer
- "description": a 1-2 sentence varied description
- "hashtags": an array of 3 to 6 lowercase tags, no '#' symbol"""

    if roster:
        lines = "\n".join(f'    - {v["id"]}: {v["style"]}' for v in roster)
        s += f"""
- "voice": pick the ONE voice id whose style best matches THIS clip's tone and energy,
  from this roster (return the id exactly):
{lines}"""
    return s


def _build_user(clip: Clip) -> str:
    bits = [
        f"Streamer/creator: {clip.creator}",
        f"Clip title: {clip.title}",
        f"Source platform: {clip.source}",
    ]
    if clip.view_count:
        bits.append(f"Original view count: {clip.view_count}")
    if clip.duration:
        bits.append(f"Clip length: {clip.duration:.0f}s")
    return "Write the commentary and metadata for this clip:\n" + "\n".join(bits)


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace:
            raw = brace.group(0)
    return json.loads(raw)


def generate(clip: Clip, llm_cfg: dict, roster: list[dict] | None = None) -> ScriptResult:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required for the transform stage (AI commentary). "
            "Set it in your .env, or disable the stage with transform.enabled: false."
        )

    system_text = _system(llm_cfg["persona"], llm_cfg["max_words"], roster)
    valid_voices = {v["id"] for v in roster} if roster else set()

    from anthropic import Anthropic

    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=llm_cfg["model"],
        max_tokens=600,
        system=[
            {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": _build_user(clip)}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    data = _extract_json(raw)
    hashtags = [h.lstrip("#").strip() for h in data.get("hashtags", []) if h.strip()]
    voice = str(data.get("voice", "")).strip()
    if voice not in valid_voices:        # invalid/missing → caller falls back to default
        voice = ""
    return ScriptResult(
        commentary=str(data.get("commentary", "")).strip(),
        title=data["title"].strip(),
        description=data.get("description", "").strip(),
        hashtags=hashtags,
        voice=voice,
        narrate=bool(data.get("narrate", True)),
        hook=str(data.get("hook", "")).strip(),
    )
