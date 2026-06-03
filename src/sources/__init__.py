from dataclasses import dataclass


@dataclass
class Clip:
    id: str
    title: str
    source: str          # "twitch" | "youtube"
    creator: str
    download_url: str    # direct mp4 URL OR page URL for yt-dlp
    duration: float | None = None
    view_count: int | None = None
