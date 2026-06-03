"""
Entry point. Usage:
  python main.py                # full pipeline (fetch → process → post if enabled)
  python main.py --dry-run      # skip posting even if posting.enabled = true
  python main.py --no-post      # alias for --dry-run
"""
import argparse
from pathlib import Path

from src.config import load_config
from src.state import State
from src.sources import Clip
from src.sources.twitch import TwitchClient, download_clip as download_twitch
from src.sources.youtube import fetch_metadata as yt_meta, download as yt_download
from src.processor.video import process as process_video


def gather_clips(cfg: dict) -> list[Clip]:
    clips: list[Clip] = []

    tw = cfg["sources"]["twitch"]
    if tw["enabled"] and tw.get("broadcasters"):
        client = TwitchClient()
        for login in tw["broadcasters"]:
            try:
                clips.extend(
                    client.get_top_clips(
                        login,
                        limit=tw["clips_per_broadcaster"],
                        period_days=tw["period_days"],
                        min_views=tw["min_views"],
                    )
                )
            except Exception as e:
                print(f"  [twitch] {login}: {e}")

    yt = cfg["sources"]["youtube"]
    if yt["enabled"]:
        for url in yt.get("urls", []):
            try:
                clips.append(yt_meta(url))
            except Exception as e:
                print(f"  [youtube] {url}: {e}")

    return clips


def download_clip(clip: Clip, dest: Path) -> Path:
    if clip.source == "twitch":
        return download_twitch(clip, dest)
    if clip.source == "youtube":
        return yt_download(clip, dest)
    raise ValueError(f"Unknown source: {clip.source}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", "--no-post", dest="dry_run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    state = State(cfg["paths"]["state"])
    downloads = Path(cfg["paths"]["downloads"])
    processed = Path(cfg["paths"]["processed"])

    print("Gathering clips…")
    clips = gather_clips(cfg)
    print(f"  found {len(clips)}")

    posted_now: list[tuple[Clip, Path]] = []
    for clip in clips:
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
            )
            posted_now.append((clip, out))
        except Exception as e:
            print(f"  failed: {e}")

    if not posted_now:
        print("Nothing new to post.")
        return

    if args.dry_run or not cfg["posting"]["enabled"]:
        print("\nReady-to-post files (posting disabled):")
        for clip, path in posted_now:
            print(f"  {path}  —  {clip.title}")
        return

    target = cfg["posting"]["target"]
    caption_tmpl = cfg["posting"]["caption_template"]
    desc_tmpl = cfg["posting"].get("description_template", caption_tmpl)

    if target == "tiktok":
        from src.poster.tiktok import TikTokPoster
        tcfg = cfg["posting"]["tiktok"]
        poster = TikTokPoster()
        for clip, path in posted_now:
            caption = caption_tmpl.format(title=clip.title, creator=clip.creator)
            print(f"  posting (tiktok): {clip.title!r}")
            publish_id = poster.post(
                path,
                caption=caption,
                privacy=tcfg["privacy"],
                disable_comment=tcfg["disable_comment"],
                disable_duet=tcfg["disable_duet"],
                disable_stitch=tcfg["disable_stitch"],
            )
            try:
                poster.wait_for_publish(publish_id)
                print(f"    published ({publish_id})")
                state.mark_posted(clip.id)
            except Exception as e:
                print(f"    status check failed: {e}")

    elif target == "youtube_shorts":
        from src.poster.youtube import YouTubeShortsPoster
        ycfg = cfg["posting"]["youtube_shorts"]
        poster = YouTubeShortsPoster()
        for clip, path in posted_now:
            title = caption_tmpl.format(title=clip.title, creator=clip.creator)
            description = desc_tmpl.format(title=clip.title, creator=clip.creator)
            print(f"  posting (youtube shorts): {title!r}")
            try:
                video_id = poster.post(
                    path,
                    title=title,
                    description=description,
                    privacy=ycfg["privacy"],
                    category_id=ycfg["category_id"],
                    tags=ycfg["tags"],
                )
                print(f"    uploaded: https://youtube.com/shorts/{video_id}")
                state.mark_posted(clip.id)
            except Exception as e:
                print(f"    upload failed: {e}")

    else:
        raise ValueError(f"Unknown posting.target: {target}")


if __name__ == "__main__":
    main()
