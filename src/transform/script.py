"""
AI commentary + metadata, grounded in the ACTUAL clip: the model is given frames from the
clip (vision) and the transcript of what was said, so titles/labels match the real moment
instead of a generic clip title.

Needs ANTHROPIC_API_KEY. Prompt caching is applied to the static instruction block.
"""
import json
import re

from ..config import env
from ..sources import Clip
from . import ScriptResult


def _system(persona: str, max_words: int, roster: list[dict] | None) -> str:
    s = f"""You are {persona}.

You are given FRAMES from a vertical short-form clip (look at them) and the TRANSCRIPT of
what the streamer said. Use both to understand what ACTUALLY happens, then write the clip's
on-screen text and metadata. Ground everything in what you see/hear — never invent events.

Return ONLY a JSON object, no prose, with these keys:
- "narrate": true/false. FALSE when the clip carries itself (streamer reacting/talking — their
  own audio is the hook; narrating over them ruins it). TRUE only to add context to a quiet or
  confusing clip. When unsure, FALSE.
- "hook": one punchy opening line, <= 7 words, a curiosity-gap or bold claim about THIS moment.
- "labels": an array of 2 to 4 SHORT editorial hype labels (2-5 words each) that narrate the
  moment on screen like a clip-page editor — e.g. "*HE LOST IT*", "BRO IS COOKED", "CHAT WENT
  CRAZY", "NO WAY". Punchy, reaction-style, specific to what's happening, no emojis.
- "commentary": spoken voiceover text used ONLY if narrate is true (else ""), <= {max_words}
  words, plain spoken sentences specific to this clip.
- "title": a punchy title (<= 80 chars) matching the moment.
- "description": a 1-2 sentence varied description.
- "hashtags": an array of 3-6 lowercase tags, no '#' symbol."""

    if roster:
        lines = "\n".join(f'    - {v["id"]}: {v["style"]}' for v in roster)
        s += f"""
- "voice": pick the ONE voice id whose style best fits this clip's tone (return the id exactly):
{lines}"""
    return s


def _build_user(clip: Clip, transcript: str) -> str:
    bits = [f"Streamer: {clip.creator}", f"Clip title: {clip.title}", f"Source: {clip.source}"]
    if clip.view_count:
        bits.append(f"Original views: {clip.view_count}")
    bits.append("Transcript of what was said: " + (transcript.strip() or "(no clear speech)"))
    return "Here are frames + info for the clip. Write its on-screen text and metadata:\n" + "\n".join(bits)


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


def generate(clip: Clip, llm_cfg: dict, roster: list[dict] | None = None,
             transcript: str = "", frames: list[str] | None = None) -> ScriptResult:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required for the transform stage. Set it in .env or "
            "disable the stage with transform.enabled: false."
        )

    system_text = _system(llm_cfg["persona"], llm_cfg["max_words"], roster)
    valid_voices = {v["id"] for v in roster} if roster else set()

    content: list[dict] = []
    for f in (frames or []):
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": f}})
    content.append({"type": "text", "text": _build_user(clip, transcript)})

    from anthropic import Anthropic

    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=llm_cfg["model"],
        max_tokens=700,
        system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    data = _extract_json(raw)
    hashtags = [h.lstrip("#").strip() for h in data.get("hashtags", []) if h.strip()]
    labels = [str(x).strip() for x in data.get("labels", []) if str(x).strip()][:4]
    voice = str(data.get("voice", "")).strip()
    if voice not in valid_voices:
        voice = ""
    return ScriptResult(
        commentary=str(data.get("commentary", "")).strip(),
        title=data["title"].strip(),
        description=data.get("description", "").strip(),
        hashtags=hashtags,
        voice=voice,
        narrate=bool(data.get("narrate", False)),
        hook=str(data.get("hook", "")).strip(),
        labels=labels,
    )
