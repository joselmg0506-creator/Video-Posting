import hashlib
from pathlib import Path

import yt_dlp

from . import Clip


def _id_for(url: str) -> str:
    return "youtube:" + hashlib.sha1(url.encode()).hexdigest()[:12]


def fetch_metadata(url: str) -> Clip:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return Clip(
        id=_id_for(url),
        title=info.get("title", "untitled"),
        source="youtube",
        creator=info.get("uploader", "unknown"),
        download_url=url,
        duration=info.get("duration"),
        view_count=info.get("view_count"),
    )


def _channel_tab_url(channel: str, tab: str = "videos") -> str:
    """Normalize '@handle', 'handle', or a full URL into a channel tab URL.
    tab = "videos" (long-form to clip) | "shorts" (already vertical) | "streams"."""
    if channel.startswith("http"):
        return channel
    handle = channel if channel.startswith("@") else f"@{channel}"
    return f"https://www.youtube.com/{handle}/{tab}"


def recent_uploads(channel: str, limit: int = 5, tab: str = "videos") -> list[Clip]:
    """List a YouTube channel's most recent uploads as Clips (metadata only, newest
    first). Uses yt-dlp flat extraction so it stays fast and needs no API key.
    Set tab="shorts" to pull the creator's already-vertical Shorts instead of long-form."""
    url = _channel_tab_url(channel, tab)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,     # list playlist entries without resolving each video
        "playlistend": limit,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    clips: list[Clip] = []
    for e in (info.get("entries") or [])[:limit]:
        vid = e.get("url") or e.get("id")
        if not vid:
            continue
        watch = vid if str(vid).startswith("http") else f"https://www.youtube.com/watch?v={vid}"
        clips.append(
            Clip(
                id=_id_for(watch),
                title=e.get("title", "untitled"),
                source="youtube",
                creator=e.get("uploader") or e.get("channel") or info.get("title", "unknown"),
                download_url=watch,
                duration=e.get("duration"),
                view_count=e.get("view_count"),
            )
        )
    return clips


def download(clip: Clip, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / f"{clip.id.replace(':', '_')}.%(ext)s")
    opts = {
        "outtmpl": out_template,
        # Prefer ≤1080p mp4 to keep processing fast
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(clip.download_url, download=True)
        path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
        return path
