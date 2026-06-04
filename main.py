"""
Entry point. Usage:
  python main.py                # full pipeline (fetch → process → transform → post if enabled)
  python main.py --dry-run      # skip posting even if posting.enabled = true
  python main.py --no-post      # alias for --dry-run
"""
import argparse
import sys
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path

from src.config import load_config
from src.state import State
from src.sources import Clip
from src.sources.twitch import TwitchClient, download_clip as download_twitch
from src.sources.youtube import (
    fetch_metadata as yt_meta,
    download as yt_download,
    recent_uploads as yt_recent,
)
from src.processor.video import process as process_video
from src.transform import transform as transform_clip


@dataclass
class PostItem:
    """A finished video plus the metadata the posters need."""
    clip: Clip
    path: Path
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    ai_label: bool = False
    voice: str = ""


def _round_robin(seqs: list) -> list:
    """Flatten sequences by taking one item from each in turn (skipping exhausted ones).
    Used twice: to order buckets so source TYPES alternate, then to interleave clips."""
    out: list = []
    for row in zip_longest(*seqs):
        out.extend(x for x in row if x is not None)
    return out


def gather_clips(cfg: dict) -> list[Clip]:
    """Pull clips into per-source buckets, order the buckets so streamer/game/YouTube
    types alternate, then round-robin the clips. Result: every run is a varied mix
    rather than one source filling the per-run cap."""
    streamer_buckets: list[list[Clip]] = []
    game_buckets: list[list[Clip]] = []
    youtube_buckets: list[list[Clip]] = []

    tw = cfg["sources"]["twitch"]
    client = None
    if tw["enabled"] and (tw.get("broadcasters") or tw.get("games")):
        try:
            client = TwitchClient()
        except Exception as e:
            print(f"  [twitch] skipped (no/invalid credentials): {e}")

    if client:
        for login in tw.get("broadcasters", []):
            try:
                streamer_buckets.append(
                    client.get_top_clips(
                        login,
                        limit=tw["clips_per_broadcaster"],
                        period_days=tw["period_days"],
                        min_views=tw["min_views"],
                    )
                )
            except Exception as e:
                print(f"  [twitch] {login}: {e}")
        for game in tw.get("games", []):
            try:
                game_buckets.append(
                    client.get_top_clips_by_game(
                        game,
                        limit=tw["clips_per_game"],
                        period_days=tw["period_days"],
                        min_views=tw["min_views"],
                    )
                )
            except Exception as e:
                print(f"  [twitch] game {game!r}: {e}")

    yt = cfg["sources"]["youtube"]
    if yt["enabled"]:
        for channel in yt.get("channels", []):
            try:
                youtube_buckets.append(
                    yt_recent(
                        channel,
                        limit=yt.get("channel_uploads_per", 2),
                        tab=yt.get("tab", "videos"),
                    )
                )
            except Exception as e:
                print(f"  [youtube] channel {channel}: {e}")
        for url in yt.get("urls", []):
            try:
                youtube_buckets.append([yt_meta(url)])
            except Exception as e:
                print(f"  [youtube] {url}: {e}")

    # Order buckets type-alternating (streamer, game, youtube, ...), then round-robin clips.
    ordered = _round_robin([streamer_buckets, game_buckets, youtube_buckets])
    return _round_robin(ordered)


def download_clip(clip: Clip, dest: Path) -> Path:
    if clip.source == "twitch":
        return download_twitch(clip, dest)
    if clip.source == "youtube":
        return yt_download(clip, dest)
    raise ValueError(f"Unknown source: {clip.source}")


def build_item(clip: Clip, processed_path: Path, cfg: dict) -> PostItem:
    """Apply the transform stage (if enabled) and return a ready-to-post item.

    With transform on, the title/description/hashtags are AI-written per clip and the
    video carries voiceover + captions. With it off, we fall back to the static
    templates over the bare 9:16 clip.
    """
    pcfg = cfg["posting"]
    if cfg.get("transform", {}).get("enabled"):
        final = processed_path.with_name(processed_path.stem + "_final.mp4")
        t = transform_clip(clip, processed_path, final, cfg)
        return PostItem(
            clip=clip,
            path=t.path,
            title=t.script.title,
            description=t.script.description,
            hashtags=t.script.hashtags,
            ai_label=t.ai_label,
            voice=t.voice,
        )

    title = pcfg["caption_template"].format(title=clip.title, creator=clip.creator)
    description = pcfg.get("description_template", pcfg["caption_template"]).format(
        title=clip.title, creator=clip.creator
    )
    return PostItem(clip=clip, path=processed_path, title=title, description=description)


def main() -> None:
    # Force UTF-8 stdout/stderr so prints never crash on non-cp1252 chars (arrows,
    # emoji/smart-quotes in AI-generated titles) when run on a default Windows console.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", "--no-post", dest="dry_run", action="store_true")
    ap.add_argument("--max-per-run", type=int, default=None,
                    help="override sources.max_per_run for this run (e.g. 1 per scheduled slot)")
    args = ap.parse_args()

    cfg = load_config()
    if args.max_per_run is not None:
        cfg["sources"]["max_per_run"] = args.max_per_run
    state = State(cfg["paths"]["state"])
    downloads = Path(cfg["paths"]["downloads"])
    processed = Path(cfg["paths"]["processed"])
    transform_on = bool(cfg.get("transform", {}).get("enabled"))

    print("Gathering clips…")
    clips = gather_clips(cfg)
    print(f"  found {len(clips)}")

    items: list[PostItem] = []
    cap = cfg["sources"].get("max_per_run") or len(clips)
    for clip in clips:
        if len(items) >= cap:
            break
        if state.is_posted(clip.id):
            print(f"  skip (already posted): {clip.id} {clip.title!r}")
            continue
        try:
            print(f"  downloading: {clip.title!r}")
            raw = download_clip(clip, downloads)
            out = processed / f"{clip.id.replace(':', '_')}.mp4"
            print(f"  processing → {out.name}")
            process_video(
                raw,
                out,
                width=cfg["processing"]["target_width"],
                height=cfg["processing"]["target_height"],
                fit=cfg["processing"]["fit_mode"],
                max_duration=cfg["processing"]["max_duration_seconds"],
                peak_trim=cfg["processing"].get("peak_trim", True),
            )
            if transform_on:
                print("  transforming (AI commentary + voiceover + captions)…")
            items.append(build_item(clip, out, cfg))
        except Exception as e:
            print(f"  failed: {e}")

    if not items:
        print("Nothing new to post.")
        return

    if args.dry_run or not cfg["posting"]["enabled"]:
        print("\nReady-to-post files (posting disabled):")
        for it in items:
            voice = f"  [voice: {it.voice}]" if it.voice else ""
            print(f"  {it.path}  —  {it.title}{voice}")
        return

    target = cfg["posting"]["target"]

    if target == "tiktok":
        from src.poster.tiktok import TikTokPoster
        tcfg = cfg["posting"]["tiktok"]
        poster = TikTokPoster()
        for it in items:
            caption = it.title
            if it.hashtags:
                caption += "\n" + " ".join(f"#{h}" for h in it.hashtags)
            print(f"  posting (tiktok): {it.title!r}")
            publish_id = poster.post(
                it.path,
                caption=caption,
                privacy=tcfg["privacy"],
                disable_comment=tcfg["disable_comment"],
                disable_duet=tcfg["disable_duet"],
                disable_stitch=tcfg["disable_stitch"],
                is_aigc=it.ai_label,
            )
            try:
                poster.wait_for_publish(publish_id)
                print(f"    published ({publish_id})")
                state.mark_posted(it.clip.id)
            except Exception as e:
                print(f"    status check failed: {e}")

    elif target == "youtube_shorts":
        from src.poster.youtube import YouTubeShortsPoster
        ycfg = cfg["posting"]["youtube_shorts"]
        poster = YouTubeShortsPoster()
        for it in items:
            title = it.title if "#shorts" in it.title.lower() else f"{it.title} #Shorts"
            title = title[:100]
            tags = list(ycfg["tags"]) + it.hashtags
            print(f"  posting (youtube shorts): {title!r}")
            try:
                video_id = poster.post(
                    it.path,
                    title=title,
                    description=it.description,
                    privacy=ycfg["privacy"],
                    category_id=ycfg["category_id"],
                    tags=tags,
                    contains_synthetic_media=it.ai_label,
                )
                print(f"    uploaded: https://youtube.com/shorts/{video_id}")
                state.mark_posted(it.clip.id)
            except Exception as e:
                print(f"    upload failed: {e}")

    else:
        raise ValueError(f"Unknown posting.target: {target}")


if __name__ == "__main__":
    main()
