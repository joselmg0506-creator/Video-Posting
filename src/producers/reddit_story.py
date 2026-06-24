"""
Story producer (channel content_type=reddit_story).

Two source modes and two visual modes, mix-and-match:
  source: reddit    -> rewrite a top Reddit post   | original -> generate an original story
  visual: gameplay  -> looped gameplay b-roll      | ai_illustrated -> per-scene Flux art

The differentiated combo is `source: original` + `visual: ai_illustrated`: fully original
(no reused-content / Reddit-licensing exposure) with a per-scene illustrated look that the
gameplay-loop crowd doesn't have. The render back-half (TTS → captions → outro) is shared
with the clips channel.

Reddit source needs REDDIT_CLIENT_ID/SECRET (unauth is 403-blocked). ai_illustrated needs
FAL_KEY (or REPLICATE_API_TOKEN). All modes need ANTHROPIC_API_KEY + internet + ffmpeg.
"""
import hashlib
import random
import tempfile
import time
from pathlib import Path

import requests

from ..config import env
from ..transform import tts as _tts
from ..transform import compose as _compose
from ..transform import endcard as _endcard
from ..transform.compose import _probe_duration
from ..transform.script import _extract_json
from . import visuals

WPM = 150
STORY_IMG_STYLE = ("cinematic digital illustration, consistent storybook art style, "
                   "moody dramatic lighting, vertical 9:16 composition, no text")

_TOKEN: str | None = None
_TOKEN_EXP: float = 0.0


# ───────────────────────────────── Reddit sourcing ────────────────────────────────────

def _ua() -> str:
    return env("REDDIT_USER_AGENT", "windows:videoposting:0.1 (by /u/videoposting)")


def _token() -> str | None:
    """App-only OAuth token (client-credentials), mirroring the Twitch app-token flow.
    Needs REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET (a 'script' app at
    https://www.reddit.com/prefs/apps). Returns None if creds are absent."""
    global _TOKEN, _TOKEN_EXP
    cid, csec = env("REDDIT_CLIENT_ID"), env("REDDIT_CLIENT_SECRET")
    if not (cid and csec):
        return None
    if _TOKEN and time.time() < _TOKEN_EXP - 60:
        return _TOKEN
    r = requests.post("https://www.reddit.com/api/v1/access_token",
                      auth=(cid, csec), data={"grant_type": "client_credentials"},
                      headers={"User-Agent": _ua()}, timeout=20)
    r.raise_for_status()
    body = r.json()
    _TOKEN = body["access_token"]
    _TOKEN_EXP = time.time() + body.get("expires_in", 3600)
    return _TOKEN


def _fetch_subreddit(sub: str, time_filter: str, limit: int = 25) -> list[dict]:
    tok = _token()
    if tok:
        base, headers = "https://oauth.reddit.com", {
            "User-Agent": _ua(), "Authorization": f"Bearer {tok}"}
    else:
        base, headers = "https://www.reddit.com", {"User-Agent": _ua()}
    r = requests.get(f"{base}/r/{sub}/top", params={"t": time_filter, "limit": limit},
                     headers=headers, timeout=20)
    r.raise_for_status()
    return [c["data"] for c in r.json().get("data", {}).get("children", [])]


def _eligible(post: dict, rc: dict) -> bool:
    if not post.get("is_self") or post.get("over_18") or post.get("stickied"):
        return False
    body = (post.get("selftext") or "").strip()
    if not body or body in ("[removed]", "[deleted]"):
        return False
    if post.get("score", 0) < rc.get("min_score", 0):
        return False
    n = len(body.split())
    return rc.get("min_words", 0) <= n <= rc.get("max_words", 10_000)


def _fetch_posts(rc: dict) -> list[dict]:
    subs = list(rc.get("subreddits", []))
    random.shuffle(subs)
    pool: list[dict] = []
    for sub in subs:
        try:
            for post in _fetch_subreddit(sub, rc.get("time_filter", "week")):
                if _eligible(post, rc):
                    pool.append(post)
        except Exception as e:
            print(f"    [reddit] r/{sub}: {e}")
    pool.sort(key=lambda p: p.get("score", 0), reverse=True)
    return pool


# ───────────────────────────────── scripting (LLM) ────────────────────────────────────

def _keys_tail(target_words: int, illustrated: bool, scenes: int) -> str:
    tail = f"""
- "narration": the spoken text (~{target_words} words), clean/advertiser-friendly, no real
  names or identifying details, ending on a line that invites comments.
- "title": a YouTube-Shorts title, <= 80 chars, hooky, NO '#'.
- "description": 1-2 sentences.
- "hashtags": 3-6 lowercase tags, no '#'.
- "hook": a 3-6 word ALL-CAPS-friendly on-screen banner."""
    if illustrated:
        tail += f"""
- "scene_prompts": an array of EXACTLY {scenes} one-sentence image prompts illustrating the
  story's beats IN ORDER. Keep characters and art style CONSISTENT across all of them. Never
  put text or letters in the images."""
    return tail


def _llm_json(system: str, user: str, llm_cfg: dict, temperature: float | None = None) -> dict:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the story channel.")
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    kwargs = dict(
        model=llm_cfg["model"], max_tokens=1500,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    if temperature is not None:
        kwargs["temperature"] = temperature
    msg = client.messages.create(**kwargs)
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)
    data["hashtags"] = [h.lstrip("#").strip() for h in data.get("hashtags", []) if h.strip()][:6]
    return data


def _write_from_post(post: dict, llm_cfg: dict, target_words: int,
                     illustrated: bool, scenes: int) -> dict:
    system = ("You rewrite Reddit stories into punchy, advertiser-friendly short-form "
              "narration for a faceless story-time channel. Open with a 1-sentence curiosity "
              "hook, condense to the essential beats, keep the twist. Return ONLY a JSON "
              "object with these keys:" + _keys_tail(target_words, illustrated, scenes))
    user = (f"Subreddit: r/{post.get('subreddit')}\nTitle: {post.get('title')}\n\n"
            f"Body:\n{(post.get('selftext') or '')[:5000]}")
    return _llm_json(system, user, llm_cfg)


def _invent_original(llm_cfg: dict, theme: str, target_words: int,
                     illustrated: bool, scenes: int, audience: str = "") -> dict:
    aud = ""
    if audience:
        aud = (f" Write it FOR {audience}: keep the language simple and age-appropriate, set it "
               "in their world (school, friends, recess, home), keep it clean and kind-hearted "
               "(no graphic violence, romance, or scary content), and make the hook and payoff "
               "easy to follow.")
    system = ("You write ORIGINAL short-form stories for a faceless story-time channel — "
              "fictional, engaging, with a strong curiosity hook and a satisfying twist. The "
              "story is your own invention (not copied from anywhere)." + aud +
              " Return ONLY a JSON object with these keys:" +
              _keys_tail(target_words, illustrated, scenes))
    user = (f"Write a fresh, surprising original story on the theme: {theme}. "
            "Make it specific and vivid, not generic.")
    return _llm_json(system, user, llm_cfg, temperature=1.0)


# ───────────────────────────────── rendering ─────────────────────────────────────────

def _render_one(story: dict, item_id: str, channel: dict, cfg: dict) -> "object":
    rc = channel["reddit_story"]
    tcfg = cfg.get("transform", {})
    ccfg = tcfg.get("captions", {})
    ecfg = tcfg.get("endcard", {})
    visual = rc.get("visual", "gameplay")
    voice = rc.get("voice") or "en-US-AndrewNeural"
    narration = (story.get("narration") or "").strip()
    if not narration:
        raise RuntimeError("empty narration")
    final = Path(cfg["paths"]["processed"]) / f"{item_id.replace(':', '_')}_final.mp4"

    with tempfile.TemporaryDirectory(prefix="vp_story_") as tmp:
        tmp_dir = Path(tmp)
        audio, words = _tts.synthesize(narration, tmp_dir / "vo", backend="edge",
                                       voice=voice, return_timings=True)
        adur = _probe_duration(audio) or (len(narration.split()) / WPM * 60)

        if visual == "ai_illustrated":
            scene_prompts = story.get("scene_prompts") or []
            if not scene_prompts:
                raise RuntimeError("ai_illustrated visual requires scene_prompts from the LLM")
            prompts = [f"{p}, {STORY_IMG_STYLE}" for p in scene_prompts]
            images = visuals.gen_images(rc.get("image_provider", "fal"),
                                        rc.get("image_model", "fal-ai/flux/schnell"),
                                        prompts, tmp_dir)
            bg = visuals.make_slideshow(images, adur + 0.4, tmp_dir / "bg.mp4", tmp_dir,
                                        music_dir=rc.get("music_dir"))
        else:
            bg = visuals.make_gameplay_bg(rc.get("broll_dir", "./data/broll_gameplay"),
                                          adur, tmp_dir / "bg.mp4")

        endcard_on = bool(ecfg.get("enabled"))
        body = (tmp_dir / "body.mp4") if endcard_on else final
        _compose.compose(
            video=bg, out=body, voiceover=audio,
            caption_words=words or None,
            captions_text=None if words else narration,
            hook_text=(story.get("hook") or None) if ccfg.get("enabled", True) else None,
            font_size=ccfg.get("font_size", 72),
            hook_duration=float(ccfg.get("hook_seconds", 2.5)),
        )
        if endcard_on:
            _endcard.append(body, final, cta_text=ecfg.get("cta_text", ""),
                            loop_seconds=float(ecfg.get("loop_seconds", 0.5)),
                            cta_font=int(ecfg.get("cta_font_size", 46)))

    from main import PostItem
    return PostItem(
        item_id=item_id, path=final, title=story.get("title", "")[:100],
        description=story.get("description", ""), hashtags=story.get("hashtags", []),
        ai_label=bool(tcfg.get("ai_label", True)), voice=voice,
        source=story.get("source", "story"), creator=story.get("creator", ""),
    )


# ───────────────────────────────── orchestration ──────────────────────────────────────

def produce(channel: dict, cfg: dict, state, cap: int) -> list:
    rc = channel.get("reddit_story", {})
    source = rc.get("source", "reddit")
    illustrated = rc.get("visual", "gameplay") == "ai_illustrated"
    scenes = int(rc.get("scenes", 5))
    target_words = max(40, int(rc.get("target_seconds", 50) / 60 * WPM))
    lcfg = cfg["transform"]["llm"]
    items: list = []

    if source == "reddit":
        print("  fetching top Reddit stories…")
        posts = _fetch_posts(rc)
        print(f"    {len(posts)} eligible post(s)")
        if not posts and not (env("REDDIT_CLIENT_ID") and env("REDDIT_CLIENT_SECRET")):
            print("    hint: Reddit blocks unauthenticated requests — create a 'script' app at "
                  "https://www.reddit.com/prefs/apps and set REDDIT_CLIENT_ID / "
                  "REDDIT_CLIENT_SECRET in .env (or use source: original).")
        for post in posts:
            if len(items) >= cap:
                break
            item_id = f"reddit:{post['id']}"
            if state.is_posted(item_id) or state.is_pending(item_id):
                continue
            try:
                story = _write_from_post(post, lcfg, target_words, illustrated, scenes)
                story["source"] = "reddit"
                story["creator"] = f"r/{post.get('subreddit')}"
                print(f"    rendering r/{post.get('subreddit')}: {post.get('title')!r}")
                items.append(_render_one(story, item_id, channel, cfg))
            except Exception as e:
                print(f"    [story] {item_id} failed: {e}")

    elif source == "original":
        themes = list(rc.get("themes") or ["an unexpected twist"])
        attempts = 0
        while len(items) < cap and attempts < cap * 3:
            attempts += 1
            theme = random.choice(themes)
            try:
                story = _invent_original(lcfg, theme, target_words, illustrated, scenes,
                                         audience=rc.get("audience", ""))
                story["source"] = "original"
                story["creator"] = ""
                item_id = "story:" + hashlib.sha1(
                    story.get("narration", "").encode()).hexdigest()[:12]
                if state.is_posted(item_id) or state.is_pending(item_id):
                    continue
                print(f"    rendering original story (theme: {theme!r})")
                items.append(_render_one(story, item_id, channel, cfg))
            except Exception as e:
                print(f"    [story] original generation failed: {e}")
    else:
        raise ValueError(f"Unknown story source: {source!r} (use 'reddit' or 'original')")

    return items
