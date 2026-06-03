"""
YouTube Shorts uploader via YouTube Data API v3.

A video auto-classifies as a Short when it's vertical (9:16) and ≤60s.
Adding "#Shorts" to the title/description further hints the algorithm.

Prerequisites (one-time):
  1. https://console.cloud.google.com → create project → enable "YouTube Data API v3"
  2. Create OAuth client (Desktop type). Download JSON → ./secrets/youtube_client_secret.json
  3. Run `python -m src.auth_youtube` once to grant access & cache tokens.
"""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..config import env

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _load_credentials() -> Credentials:
    token_file = env("YOUTUBE_TOKEN_FILE", "./secrets/youtube_token.json")
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
    def __init__(self):
        self._service = build("youtube", "v3", credentials=_load_credentials())

    def post(
        self,
        video_path: Path,
        title: str,
        description: str,
        privacy: str = "private",
        category_id: str = "24",
        tags: list[str] | None = None,
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
            },
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = self._service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = None
        while response is None:
            _status, response = request.next_chunk()
        return response["id"]
