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
