import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yt_dlp

from . import Clip
from ..config import env

HELIX = "https://api.twitch.tv/helix"
OAUTH = "https://id.twitch.tv/oauth2/token"


def _parse_clips(data: list[dict], limit: int, min_views: int,
                 languages: set[str] | None = None) -> list[Clip]:
    """Turn raw Helix clip objects (already most-viewed first) into Clips.
    languages (e.g. {"en"}) keeps only clips whose stream language matches."""
    clips: list[Clip] = []
    for c in data:
        if c.get("view_count", 0) < min_views:
            continue
        if languages and (c.get("language", "")[:2].lower() not in languages):
            continue
        clips.append(
            Clip(
                id=f"twitch:{c['id']}",
                title=c["title"],
                source="twitch",
                creator=c["broadcaster_name"],
                download_url=c["url"],   # Twitch clip page; yt-dlp resolves the mp4
                duration=c.get("duration"),
                view_count=c.get("view_count"),
            )
        )
        if len(clips) >= limit:
            break
    return clips


class TwitchClient:
    def __init__(self):
        self.client_id = env("TWITCH_CLIENT_ID", required=True)
        self.client_secret = env("TWITCH_CLIENT_SECRET", required=True)
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _token_valid(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        r = requests.post(
            OAUTH,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + body["expires_in"]
        return self._token

    def _headers(self) -> dict:
        return {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self._token_valid()}",
        }

    def get_user_id(self, login: str) -> str | None:
        r = requests.get(
            f"{HELIX}/users",
            headers=self._headers(),
            params={"login": login},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()["data"]
        return data[0]["id"] if data else None

    def _fetch_clips(self, selector: dict, limit: int, period_days: int) -> list[dict]:
        """Raw Helix clips (most-viewed first) for a broadcaster_id or game_id selector
        over the last `period_days`."""
        now = datetime.now(timezone.utc)
        params = {
            **selector,
            "first": min(max(limit * 3, limit), 100),
            "started_at": (now - timedelta(days=period_days)).isoformat(),
            "ended_at": now.isoformat(),
        }
        r = requests.get(f"{HELIX}/clips", headers=self._headers(), params=params, timeout=15)
        r.raise_for_status()
        return r.json()["data"]

    def get_top_clips(
        self,
        broadcaster_login: str,
        limit: int = 5,
        period_days: int = 1,
        min_views: int = 0,
        languages: set[str] | None = None,
    ) -> list[Clip]:
        user_id = self.get_user_id(broadcaster_login)
        if not user_id:
            return []
        return _parse_clips(
            self._fetch_clips({"broadcaster_id": user_id}, limit, period_days),
            limit,
            min_views,
            languages,
        )

    def get_game_id(self, game_name: str) -> str | None:
        r = requests.get(
            f"{HELIX}/games",
            headers=self._headers(),
            params={"name": game_name},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()["data"]
        return data[0]["id"] if data else None

    def get_top_clips_by_game(
        self,
        game_name: str,
        limit: int = 5,
        period_days: int = 1,
        min_views: int = 0,
        languages: set[str] | None = None,
    ) -> list[Clip]:
        """Top clips for an entire game (streamer-agnostic) — the engine for a daily
        'best of <game>' highlights feed."""
        game_id = self.get_game_id(game_name)
        if not game_id:
            return []
        return _parse_clips(
            self._fetch_clips({"game_id": game_id}, limit, period_days),
            limit,
            min_views,
            languages,
        )


def download_clip(clip: Clip, dest_dir: Path) -> Path:
    """Use yt-dlp to resolve and download the Twitch clip mp4."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(dest_dir / f"{clip.id.replace(':', '_')}.%(ext)s")
    opts = {
        "outtmpl": out_template,
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(clip.download_url, download=True)
        return Path(ydl.prepare_filename(info))
