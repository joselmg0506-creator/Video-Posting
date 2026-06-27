"""
YouTube Shorts uploader via YouTube Data API v3.

A video auto-classifies as a Short when it's vertical (9:16) and ≤60s.
Adding "#Shorts" to the title/description further hints the algorithm.

Prerequisites (one-time):
  1. https://console.cloud.google.com → create project → enable "YouTube Data API v3"
  2. Create OAuth client (Desktop type). Download JSON → ./secrets/youtube_client_secret.json
  3. Run `python -m src.auth_youtube` once to grant access & cache tokens.
"""
import socket
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..config import env

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",   # read stats for the metrics digest
]

MAX_UPLOAD_RETRIES = 5
RETRYABLE_STATUS = {500, 502, 503, 504}


class QuotaExceeded(RuntimeError):
    """The YouTube Data API daily quota is exhausted. videos.insert costs ~1600 of the
    10,000 default units/day (~6 uploads/day), so the caller should STOP the run rather
    than retry and burn more quota."""


def _is_quota_error(e: HttpError) -> bool:
    resp = getattr(e, "resp", None)
    return resp is not None and resp.status == 403 and "quota" in str(e).lower()


def _load_credentials(token_file: str | None = None) -> Credentials:
    token_file = token_file or env("YOUTUBE_TOKEN_FILE", "./secrets/youtube_token.json")
    path = Path(token_file)
    if not path.exists():
        raise RuntimeError(
            f"No cached YouTube token at {path}. Run `python -m src.auth_youtube` first."
        )
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
    return creds


class YouTubeShortsPoster:
    def __init__(self, token_file: str | None = None):
        self._service = build("youtube", "v3", credentials=_load_credentials(token_file))

    def post(
        self,
        video_path: Path,
        title: str,
        description: str,
        privacy: str = "private",
        category_id: str = "24",
        tags: list[str] | None = None,
        contains_synthetic_media: bool = False,
        thumbnail_path: Path | None = None,
    ) -> str:
        body = {
            "snippet": {
                "title": title[:100],   # YouTube title max
                "description": description[:5000],
                "tags": tags or [],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
                # AI/altered-content disclosure (Data API v3, since 2024-10-30).
                "containsSyntheticMedia": contains_synthetic_media,
            },
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = self._service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        # Drive the resumable upload. On a transient network/5xx error we retry the SAME
        # request — next_chunk() resumes where it left off, so retrying can't double-post.
        # A 403 quota error is fatal for the run and re-raised as QuotaExceeded.
        response = None
        attempt = 0
        while response is None:
            try:
                _status, response = request.next_chunk()
            except HttpError as e:
                if _is_quota_error(e):
                    raise QuotaExceeded(str(e)) from e
                if e.resp.status in RETRYABLE_STATUS and attempt < MAX_UPLOAD_RETRIES:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise
            except (socket.timeout, ConnectionError, OSError) as e:
                if attempt >= MAX_UPLOAD_RETRIES:
                    raise
                attempt += 1
                time.sleep(min(2 ** attempt, 30))

        video_id = response["id"]
        # Custom cover, best-effort: the video is already live, so a thumbnail failure (channel not
        # enabled for custom thumbnails, quota, etc.) must NEVER fail the post — just log and move on.
        if thumbnail_path and Path(thumbnail_path).exists():
            try:
                self._service.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
                ).execute()
                print("    set custom thumbnail")
            except Exception as e:
                print(f"    thumbnail not set ({type(e).__name__}: {str(e)[:120]})")
        return video_id
