"""
Entry point.

Runs one or more CHANNELS (see `channels:` in config.yaml). Each channel has a
`content_type` (clips | reddit_story | ai_character) that selects a producer, plus its
own YouTube OAuth token and posting settings. The shared back-half (render → captions →
post) is the same for every channel; only the producer (the front-half) differs.

Usage:
  python main.py                 # run every enabled channel (post if posting.enabled)
  python main.py --dry-run        # build everything but never post
  python main.py --channel reddit # run only the named channel
  python main.py --max-per-run 1  # cap items per channel this run
  python main.py --metrics        # post a metrics digest instead of running the pipeline
  python main.py --music-edit      # render the beat-synced music edit
  python main.py --clear-pending   # release clips parked after an interrupted upload
"""
import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

from src import notify
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
from src.transform import ClipRejected


@dataclass
class PostItem:
    """A finished 9:16 video plus the metadata the posters need. Channel-agnostic:
    `item_id` is the stable dedup key (e.g. twitch:…, reddit:…, char:…), and creator/
    source are for attribution + metrics (empty for fully-generated content)."""
    item_id: str
    path: Path
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    ai_label: bool = False
    voice: str = ""
    creator: str = ""
    source: str = ""


# ─────────────────────────── clip sourcing (channel: clips) ───────────────────────────

def _round_robin(seqs: list) -> list:
    """Flatten sequences by taking one item from each in turn (skipping exhausted ones).
    Used twice: to order buckets so source TYPES alternate, then to interleave clips."""
    out: list = []
    for row in zip_longest(*seqs):
        out.extend(x for x in row if x is not None)
    return out


def _norm_creator(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _creator_rank(creator: str, priority: list[str]) -> int:
    """Position of this clip's creator in the priority list (0 = highest). Matched loosely
    (case/spacing/handle-insensitive substring either way), so '2xrakai' ~ 'RaKai',
    '@KaiCenat' ~ 'kaicenat'. Unlisted creators sort last (rank = len)."""
    c = _norm_creator(creator)
    for i, p in enumerate(priority):
        pn = _norm_creator(p)
        if pn and (pn in c or c in pn):
            return i
    return len(priority)


def gather_clips(cfg: dict) -> list[Clip]:
    """Pull clips into per-source buckets, order the buckets so streamer/game/YouTube
    types alternate, then round-robin the clips. Result: every run is a varied mix
    rather than one source filling the per-run cap."""
    streamer_buckets: list[list[Clip]] = []
    game_buckets: list[list[Clip]] = []
    youtube_buckets: list[list[Clip]] = []

    tw = cfg["sources"]["twitch"]
    langs = {s[:2].lower() for s in tw.get("languages", ["en"]) if s} or None
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
                        languages=langs,
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
                        languages=langs,
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

    # Staged YouTube clips (downloaded locally, served from a Release) — this is how YouTube
    # creators reach the cloud, where live YouTube download is bot-blocked. Treated as a youtube
    # bucket so the creator-priority sort still applies to them.
    if cfg["sources"].get("youtube_staged", {}).get("enabled", True):
        try:
            from src.sources.staged import available_clips
            staged = available_clips(cfg)
            if staged:
                youtube_buckets.append(staged)
                print(f"  [staged] {len(staged)} YouTube clip(s) from the cloud cache")
        except Exception as e:
            print(f"  [staged] unavailable: {e}")

    # Order buckets type-alternating (streamer, game, youtube, ...), then round-robin clips.
    ordered = _round_robin([streamer_buckets, game_buckets, youtube_buckets])
    clips = _round_robin(ordered)
    # Creator hierarchy: clip the top streamers/YouTubers FIRST, then the rest. A stable sort
    # keeps the round-robin variety WITHIN each priority rank.
    priority = cfg["sources"].get("priority_creators") or []
    if priority:
        clips.sort(key=lambda c: _creator_rank(getattr(c, "creator", ""), priority))
    return clips


def download_clip(clip: Clip, dest: Path) -> Path:
    if clip.source == "twitch":
        return download_twitch(clip, dest)
    if clip.source == "youtube":
        return yt_download(clip, dest)
    if clip.source == "youtube_staged":
        from src.sources.staged import download_staged
        return download_staged(clip, dest)
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
            item_id=clip.id,
            path=t.path,
            title=t.script.title,
            description=t.script.description,
            hashtags=t.script.hashtags,
            ai_label=t.ai_label,
            voice=t.voice,
            creator=clip.creator,
            source=clip.source,
        )

    title = pcfg["caption_template"].format(title=clip.title, creator=clip.creator)
    description = pcfg.get("description_template", pcfg["caption_template"]).format(
        title=clip.title, creator=clip.creator
    )
    return PostItem(item_id=clip.id, path=processed_path, title=title,
                    description=description, creator=clip.creator, source=clip.source)


def produce_clips(channel: dict, cfg: dict, state: State, cap: int) -> list[PostItem]:
    """Producer for content_type=clips: gather → download → process → transform."""
    downloads = Path(cfg["paths"]["downloads"])
    processed = Path(cfg["paths"]["processed"])
    transform_on = bool(cfg.get("transform", {}).get("enabled"))

    print("  gathering clips…")
    clips = gather_clips(cfg)
    print(f"    found {len(clips)}")

    items: list[PostItem] = []
    for clip in clips:
        if len(items) >= cap:
            break
        if state.is_posted(clip.id):
            print(f"    skip (already posted): {clip.id} {clip.title!r}")
            continue
        if state.is_pending(clip.id):
            print(f"    skip (pending — prior run interrupted mid-upload; "
                  f"`--clear-pending` to release): {clip.id}")
            continue
        try:
            print(f"    downloading: {clip.title!r}")
            raw = download_clip(clip, downloads)
            if clip.source == "youtube_staged":
                out = raw   # already 9:16 + trimmed when it was staged locally — skip re-processing
            else:
                out = processed / f"{clip.id.replace(':', '_')}.mp4"
                print(f"    processing → {out.name}")
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
                print("    transforming (AI commentary + voiceover + captions)…")
            item = build_item(clip, out, cfg)
            if "ai_label" in channel:        # per-channel override of the AI-disclosure flag
                item.ai_label = bool(channel["ai_label"])
            items.append(item)
        except ClipRejected as e:
            print(f"    skip (low quality): {e}")
        except Exception as e:
            print(f"    failed: {e}")
    return items


def produce(channel: dict, cfg: dict, state: State, cap: int) -> list[PostItem]:
    """Dispatch a channel to its producer based on content_type."""
    ct = channel["content_type"]
    if ct == "clips":
        return produce_clips(channel, cfg, state, cap)
    if ct == "reddit_story":
        from src.producers.reddit_story import produce as produce_reddit
        return produce_reddit(channel, cfg, state, cap)
    if ct == "story_film":
        from src.producers.story_film import produce as produce_film
        return produce_film(channel, cfg, state, cap)
    if ct == "ai_character":
        from src.producers.ai_character import produce as produce_character
        return produce_character(channel, cfg, state, cap)
    if ct == "brainrot_movie":
        from src.producers.brainrot_movie import produce as produce_brmovie
        return produce_brmovie(channel, cfg, state, cap)
    raise ValueError(f"Unknown content_type: {ct!r}")


# ──────────────────────────────────── posting ────────────────────────────────────────

def _post_youtube(items: list[PostItem], channel: dict, cfg: dict,
                  state: State, notif_on: bool) -> None:
    from src.poster.youtube import YouTubeShortsPoster, QuotaExceeded
    ycfg = channel.get("youtube") or cfg["posting"]["youtube_shorts"]
    poster = YouTubeShortsPoster(channel.get("token_file"))
    posted = 0
    for it in items:
        title = it.title if "#shorts" in it.title.lower() else f"{it.title} #Shorts"
        title = title[:100]
        tags = list(ycfg.get("tags", [])) + it.hashtags
        print(f"  posting (youtube shorts): {title!r}")
        state.begin(it.item_id)   # durable in-progress marker BEFORE the API call
        try:
            video_id = poster.post(
                it.path,
                title=title,
                description=it.description,
                privacy=ycfg.get("privacy", "private"),
                category_id=ycfg.get("category_id", "24"),
                tags=tags,
                contains_synthetic_media=it.ai_label,
            )
        except QuotaExceeded as e:
            state.clear_pending(it.item_id)   # rejected before upload → safe to retry later
            print(f"    quota exhausted — stopping channel: {e}")
            notify.send(content=f"🛑 YouTube daily quota exhausted on '{channel['name']}' — "
                                "stopping; remaining items retry next run.", enabled=notif_on)
            break
        except Exception as e:
            # Upload may have partially landed → leave PENDING so we never double-post.
            print(f"    upload failed (left pending for review): {e}")
            notify.send(content=f"❌ Upload interrupted [{channel['name']}]: {title[:80]} — {e}",
                        enabled=notif_on)
            continue
        url = f"https://youtube.com/shorts/{video_id}"
        print(f"    uploaded: {url}")
        state.record_post(
            it.item_id, video_id=video_id, url=url, title=title,
            creator=it.creator, source=it.source, channel=channel["name"],
            narrated=bool(it.voice), voice=it.voice,
            posted_at=datetime.now(timezone.utc).isoformat(),
        )
        notify.send(
            embeds=[notify.posted_embed(title, url, it.creator, it.source,
                                        bool(it.voice), it.voice)],
            enabled=notif_on,
        )
        posted += 1
    notify.send(content=f"▶️ '{channel['name']}' complete — {posted} Short(s) posted.",
                enabled=notif_on)


def _post_tiktok(items: list[PostItem], channel: dict, cfg: dict,
                 state: State, notif_on: bool) -> None:
    from src.poster.tiktok import TikTokPoster
    tcfg = channel.get("tiktok") or cfg["posting"]["tiktok"]
    poster = TikTokPoster()
    for it in items:
        caption = it.title
        if it.hashtags:
            caption += "\n" + " ".join(f"#{h}" for h in it.hashtags)
        print(f"  posting (tiktok): {it.title!r}")
        state.begin(it.item_id)
        try:
            publish_id = poster.post(
                it.path,
                caption=caption,
                privacy=tcfg["privacy"],
                disable_comment=tcfg["disable_comment"],
                disable_duet=tcfg["disable_duet"],
                disable_stitch=tcfg["disable_stitch"],
                is_aigc=it.ai_label,
            )
            poster.wait_for_publish(publish_id)
            print(f"    published ({publish_id})")
            state.mark_posted(it.item_id)
        except Exception as e:
            print(f"    post failed (left pending for review): {e}")
            notify.send(content=f"❌ TikTok post interrupted [{channel['name']}]: "
                                f"{it.title[:80]} — {e}", enabled=notif_on)


# ─────────────────────────────────── orchestration ────────────────────────────────────

def _default_channels(cfg: dict) -> list[dict]:
    """Back-compat: if config has no `channels:` block, synthesize a single clips
    channel from the legacy `posting`/`sources` config so old configs still run."""
    p = cfg.get("posting", {})
    return [{
        "name": "clips",
        "content_type": "clips",
        "enabled": True,
        "target": p.get("target", "youtube_shorts"),
        "token_file": None,
        "max_per_run": cfg.get("sources", {}).get("max_per_run", 3),
        "youtube": p.get("youtube_shorts"),
        "tiktok": p.get("tiktok"),
    }]


def run_channel(channel: dict, cfg: dict, state: State, args, notif_on: bool) -> None:
    ct = channel["content_type"]
    cap = (args.max_per_run if args.max_per_run is not None
           else channel.get("max_per_run") or cfg.get("sources", {}).get("max_per_run", 3))
    print(f"\n=== channel '{channel['name']}' ({ct}) — up to {cap} ===")

    items = produce(channel, cfg, state, cap)[:cap]
    if not items:
        print("  nothing new to post.")
        return

    if args.dry_run or not cfg["posting"]["enabled"]:
        why = "--dry-run" if args.dry_run else "posting.enabled=false"
        print(f"  ready-to-post ({why} — not posting):")
        for it in items:
            v = f"  [voice: {it.voice}]" if it.voice else ""
            print(f"    {it.path}  —  {it.title}{v}")
        return

    target = channel.get("target", "youtube_shorts")
    if target == "youtube_shorts":
        _post_youtube(items, channel, cfg, state, notif_on)
    elif target == "tiktok":
        _post_tiktok(items, channel, cfg, state, notif_on)
    else:
        raise ValueError(f"Unknown target for channel {channel['name']}: {target!r}")


def _cleanup_media(cfg: dict) -> None:
    """Delete transient LOCAL media (downloaded + rendered *.mp4) older than
    paths.keep_media_days, to free disk. NEVER touches YouTube uploads, the dedup state, or
    source assets (b-roll / gameplay / music) — only the throwaway local copies in downloads/
    and processed/, which are safe to drop: YouTube already has the posted videos, and
    state.json (untouched) tracks what's been posted so nothing re-uploads."""
    import time
    days = (cfg.get("paths", {}).get("keep_media_days") or 0)
    if days <= 0:
        return
    cutoff = time.time() - days * 86400
    removed = 0
    for key in ("downloads", "processed"):      # ONLY these two dirs; ONLY *.mp4
        d = Path(cfg["paths"].get(key, ""))
        if not d.exists():
            continue
        for f in d.glob("*.mp4"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    if removed:
        print(f"  cleaned {removed} local media file(s) older than {days}d (YouTube untouched)")


def main() -> None:
    # Force UTF-8 stdout/stderr so prints never crash on non-cp1252 chars (arrows,
    # emoji/smart-quotes in AI-generated titles) when run on a default Windows console.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", "--no-post", dest="dry_run", action="store_true")
    ap.add_argument("--max-per-run", type=int, default=None,
                    help="override per-channel max_per_run for this run")
    ap.add_argument("--channel", default=None,
                    help="run only the channel with this name (default: all enabled)")
    ap.add_argument("--metrics", action="store_true",
                    help="post a metrics digest of recent videos instead of running the pipeline")
    ap.add_argument("--music-edit", dest="music_edit", action="store_true",
                    help="render the beat-synced music edit instead of the clip pipeline")
    ap.add_argument("--clear-pending", dest="clear_pending", action="store_true",
                    help="release clips parked 'pending' after an interrupted upload, then exit")
    ap.add_argument("--dashboard", action="store_true",
                    help="build + open an HTML analytics dashboard across all channels, then exit")
    ap.add_argument("--no-open", dest="no_open", action="store_true",
                    help="with --dashboard, build the file but don't auto-open it")
    ap.add_argument("--suggestions", action="store_true",
                    help="generate competitor-aware improvement tips (data/suggestions.json) and exit")
    ap.add_argument("--stage-youtube", dest="stage_youtube", action="store_true",
                    help="download top YouTube clips locally + push to the cloud 'yt-clips' "
                         "Release (run on your laptop; only stages, never posts)")
    args = ap.parse_args()

    cfg = load_config()
    state = State(cfg["paths"]["state"])
    notif_on = cfg.get("notifications", {}).get("discord", {}).get("enabled", False)

    if args.clear_pending:
        pending = list(state.data.get("uploading", []))
        for cid in pending:
            state.clear_pending(cid)
        print(f"Cleared {len(pending)} pending item(s): {pending}" if pending
              else "No pending items to clear.")
        return

    if args.music_edit:
        from src.musicedit import make
        print("Rendering music edit…")
        make(cfg)
        return

    if args.metrics:
        from src.metrics import digest
        digest(state, cfg)
        return

    if args.dashboard:
        from src.dashboard_html import build
        build(state, cfg, open_after=not args.no_open)
        return

    if args.suggestions:
        from src.suggestions import generate
        generate(state, cfg)
        return

    if args.stage_youtube:
        from src.sources.staged import stage
        stage(state, cfg)
        return

    _cleanup_media(cfg)   # free disk: prune old local downloads/renders (never YouTube/state)

    channels = cfg.get("channels") or _default_channels(cfg)
    if args.channel:
        channels = [c for c in channels if c.get("name") == args.channel]
        if not channels:
            print(f"No channel named {args.channel!r} in config.")
            return

    for ch in channels:
        if not ch.get("enabled"):
            continue
        try:
            run_channel(ch, cfg, state, args, notif_on)
        except Exception as e:
            # Isolate channels: one failing (e.g. an API outage) must not abort the rest.
            import traceback
            traceback.print_exc()
            notify.send(content=f"🛑 Channel '{ch.get('name')}' crashed: "
                                f"{type(e).__name__}: {e}", enabled=notif_on)


if __name__ == "__main__":
    main()
