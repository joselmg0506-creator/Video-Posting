"""
Brainrot-movie producer — a connected ANIMATED Italian-brainrot mini-film where the
CHARACTERS TALK in their own absurd Italian-accented voices (not one English narrator over
the top). Each scene = one character speaking a punchy line, on a Flux still that's animated
into a moving clip; scenes are concatenated into a short film with karaoke captions.

Front-half for content_type=brainrot_movie:
  1. LLM writes a connected brainrot story told through DIALOGUE: a cast of original creatures
     (+ optional famous cameo), and per-scene {speaker, line, motion}. Lines are short, heavy
     clear simple English (the Italian-brainrot accent comes from the VOICE, not mangled text).
  2. Each character gets a distinct Italian edge-tts voice, so the voice matches who's on screen.
  3. Per scene: Flux still -> fal image-to-video (moving clip) -> the speaker's line in their
     Italian voice + karaoke caption, composited onto the clip.
  4. Scenes concatenated into the film + loop-back outro.

Needs ANTHROPIC_API_KEY + FAL_KEY (+ credit; image-to-video is the paid step) + internet + ffmpeg.
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

# Distinct Italian edge-tts voices assigned per character (by index) so each creature has its
# own accented voice. Italian voices reading English text give the brainrot Italian-accent vibe.
ITALIAN_VOICES = ["it-IT-DiegoNeural", "it-IT-IsabellaNeural", "it-IT-ElsaNeural"]

IMG_STYLE = ("cinematic 3D render, surreal Italian-brainrot character, dramatic moody "
             "atmospheric lighting, highly detailed, expressive emotional face, painterly "
             "photoreal textures, depth of field, vertical 9:16, centered subject")
FAMOUS = ("Tung Tung Tung Sahur, Ballerina Cappuccina, Tralalero Tralala, Bombardiro Crocodilo")


def _system(scenes: int) -> str:
    return f"""You write SHORT connected Italian-brainrot stories told through CHARACTER DIALOGUE
(exactly {scenes} scenes). The genre: the famous Italian-brainrot meme creatures (absurd
animal + object mashups) who TALK in heavy Italian-accented English. Tell a tiny CONNECTED
story — a beginning, a turn, and a punchy payoff — where the characters' spoken lines drive
the plot (NOT a narrator describing it). Keep it EASY TO FOLLOW: a clear setup, ONE simple
twist, and an obvious payoff, so a first-time viewer understands exactly what's happening from
the spoken lines and on-screen captions alone.

Cast: STAR the actual famous Italian-brainrot characters ({FAMOUS}) as the leads — pick 2-3.
You MAY add one original creature too. For EACH character, describe its canonical look exactly
in "appearance" so the image generator renders the right creature (e.g. Tralalero Tralala = a
blue shark wearing Nike sneakers; Ballerina Cappuccina = a ballerina with a cappuccino-cup
head; Tung Tung Tung Sahur = a wooden baseball-bat creature with a face holding a bat;
Bombardiro Crocodilo = a green military-bomber-plane crocodile hybrid).

Return ONLY a JSON object:
- "title": <= 80 chars, hooky, NO '#'. ALL-CAPS the character names plus a key word, add ONE
  emoji, and a NUMBER when it fits (e.g. "BOMBARDIRO vs CAPPUCCINA: 3 SECONDS TO CHAOS 💥") —
  the top Italian-brainrot Shorts use ALL-CAPS, emojis, and numbers.
- "description": 1-2 sentences.
- "hashtags": 3-6 lowercase tags, no '#' (include brainrot, italianbrainrot).
- "hook": a 3-6 word ALL-CAPS on-screen banner.
- "characters": array of 2-3 {{"name", "appearance"}} — "appearance" is a DETAILED canonical
  visual description in a glossy 3D-render style; reused every scene so the creature stays the
  same.
- "scenes": an array of EXACTLY {scenes} scene objects IN ORDER, each
  {{"description", "present", "motion", "speaker", "line"}}:
    - "description": the SPECIFIC dramatic scene the line is about — show the speaker creature
      IN that exact moment/action (e.g. if the line threatens to feed someone to the crocodiles,
      show that creature looming over crocodiles; if it reveals a prophecy, show the prophecy).
      The PICTURE must literally illustrate what is being SAID in this scene's line — vivid and
      specific, never a generic standing portrait — so the visuals always track the story.
    - "present": array of character names visible here (must include the speaker).
    - "motion": how things move in this shot (used only if animation is on; otherwise ignored).
    - "speaker": the ONE character name who talks in this scene.
    - "line": what the speaker SAYS — SHORT (<= 12 words), in CLEAR, SIMPLE, CORRECT ENGLISH
      that is easy to read as a caption and easy to follow. The Italian-brainrot flavor comes
      from the absurd characters and the Italian VOICE — do NOT mangle spelling or fake an
      accent in the text (write "The prophecy is real!", NOT "the prophecy it is-a real"). One
      short signature like "Mamma mia!" is okay, but the sentence itself must be plain English.
  Each scene's picture must show exactly what its line is about, and the lines must form a
  connected story in order."""


def _write_movie(llm_cfg: dict, scenes: int) -> dict:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the brainrot_movie channel.")
    from anthropic import Anthropic
    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=llm_cfg["model"], max_tokens=2000, temperature=1.0,
        system=[{"type": "text", "text": _system(scenes), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   f"Write brainrot film #{random.randint(1, 9_999_999)}. Loud, weird, and "
                   "different from the last one."}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    data = _extract_json(raw)
    data["hashtags"] = [h.lstrip("#").strip() for h in data.get("hashtags", []) if h.strip()][:6]
    if not data.get("scenes"):
        raise RuntimeError("LLM returned no scenes")
    if not data.get("characters"):
        raise RuntimeError("LLM returned no characters")
    return data


_NORM_VF = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1")


def _render_one(movie: dict, item_id: str, channel: dict, cfg: dict) -> "object":
    bc = channel["brainrot_movie"]
    tcfg = cfg.get("transform", {})
    ccfg = tcfg.get("captions", {})
    ecfg = tcfg.get("endcard", {})
    img_model = bc.get("image_model", "fal-ai/flux/schnell")
    vid_model = bc.get("video_model", "fal-ai/ltx-video-13b-distilled/image-to-video")
    num_frames = int(bc.get("num_frames", 97))
    animate_mode = bool(bc.get("animate", False))   # False = cheap synced STILLS; True = LTX video

    chars = movie["characters"]
    cast_app = {c["name"]: c.get("appearance", "") for c in chars if c.get("name")}
    char_voice = {c["name"]: ITALIAN_VOICES[i % len(ITALIAN_VOICES)]
                  for i, c in enumerate(chars)}
    default_voice = ITALIAN_VOICES[0]
    final = Path(cfg["paths"]["processed"]) / f"{item_id.replace(':', '_')}_final.mp4"

    with tempfile.TemporaryDirectory(prefix="vp_brmovie_") as tmp:
        tmp_dir = Path(tmp)
        scene_videos: list[Path] = []
        for i, sc in enumerate(movie["scenes"]):
            present = [cast_app[n] for n in sc.get("present", []) if n in cast_app]
            img = ", ".join(p for p in [IMG_STYLE, sc.get("description", "")] if p)
            if present:
                img += ", featuring " + "; ".join(present)
            img += ", no text, no watermark"

            # the speaker's line, synthesized FIRST so (in stills mode) the picture can be shown
            # for exactly the length of the line — i.e. the picture MATCHES what's being said.
            speaker = sc.get("speaker") or (chars[0]["name"] if chars else "")
            voice = char_voice.get(speaker, default_voice)
            line = (sc.get("line") or "").strip()
            audio, words = (None, None)
            if line:
                audio, words = _tts.synthesize(line, tmp_dir / f"vo_{i}", backend="edge",
                                               voice=voice, return_timings=True)
            line_dur = (_probe_duration(audio) if audio else None) or 3.0

            clip = tmp_dir / f"clip_{i}.mp4"
            if animate_mode:
                # animated: still -> fal image-to-video (retry once on a flaky response) -> normalize
                url = visuals.gen_image_urls(img_model, [img])[0]
                motion = (sc.get("motion") or "dynamic motion") + ", chaotic brainrot energy, smooth animation"
                raw = None
                for attempt in range(2):
                    try:
                        raw = visuals.animate(url, motion, tmp_dir / f"raw_{i}.mp4",
                                              model=vid_model, num_frames=num_frames)
                        break
                    except Exception as e:
                        if attempt == 1:
                            raise
                        print(f"      scene {i} animate retry ({e})")
                visuals._run(["ffmpeg", "-y", "-i", str(raw), "-an", "-vf", _NORM_VF,
                              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                              "-pix_fmt", "yuv420p", str(clip)])
            else:
                # stills (cheap, default): one dramatic picture shown for the length of its line
                still = visuals.gen_images("fal", img_model, [img], tmp_dir)[0]
                visuals.still_clip(still, line_dur + 0.4, clip)

            # composite: line audio + karaoke caption on the clip (hook only on scene 0)
            sv = tmp_dir / f"scene_{i}.mp4"
            _compose.compose(
                video=clip, out=sv, voiceover=audio,
                caption_words=words or None, captions_text=None if words else (line or None),
                hook_text=(movie.get("hook") or None) if (i == 0 and ccfg.get("enabled", True)) else None,
                font_size=ccfg.get("font_size", 72),
                hook_duration=float(ccfg.get("hook_seconds", 2.5)),
            )
            scene_videos.append(sv)

        # concat the scenes (re-encode for clean A/V across cuts)
        listing = tmp_dir / "scenes.txt"
        listing.write_text("".join(f"file '{p.name}'\n" for p in scene_videos), encoding="utf-8")
        endcard_on = bool(ecfg.get("enabled"))
        body = (tmp_dir / "body.mp4") if endcard_on else final
        visuals._run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "scenes.txt",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                      "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-movflags", "+faststart",
                      str(body)], cwd=str(tmp_dir))
        if endcard_on:
            _endcard.append(body, final, cta_text=ecfg.get("cta_text", ""),
                            loop_seconds=float(ecfg.get("loop_seconds", 0.5)),
                            cta_font=int(ecfg.get("cta_font_size", 46)))

    from main import PostItem
    cast_names = ", ".join(c.get("name", "") for c in chars)
    return PostItem(
        item_id=item_id, path=final, title=movie.get("title", "")[:100],
        description=movie.get("description", ""), hashtags=movie.get("hashtags", []),
        ai_label=bool(tcfg.get("ai_label", True)), voice="it-IT (per-character)",
        source="brainrot", creator=cast_names,
    )


def produce(channel: dict, cfg: dict, state, cap: int) -> list:
    bc = channel.get("brainrot_movie", {})
    scenes = int(bc.get("scenes", 5))
    lcfg = cfg["transform"]["llm"]

    items: list = []
    attempts = 0
    while len(items) < cap and attempts < cap * 3:
        attempts += 1
        try:
            movie = _write_movie(lcfg, scenes)
            item_id = "brmovie:" + hashlib.sha1(
                (movie.get("title", "") + str(movie.get("scenes"))).encode()).hexdigest()[:12]
            if state.is_posted(item_id) or state.is_pending(item_id):
                continue
            cast = ", ".join(c.get("name", "?") for c in movie.get("characters", []))
            print(f"    directing brainrot dialogue film (cast: {cast}; {scenes} talking scenes)")
            items.append(_render_one(movie, item_id, channel, cfg))
        except Exception as e:
            print(f"    [brainrot_movie] generation failed: {e}")
    return items
