"""
TikTok Content Posting API client.

Prerequisites (one-time):
  1. Register an app at https://developers.tiktok.com/
  2. Add the "Content Posting API" product and request the `video.publish` scope.
  3. Apply for production review — sandbox accounts can only post to SELF_ONLY.
  4. Run `python -m src.auth_tiktok` to complete OAuth and grab tokens.

Docs:
  https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
"""
import time
from pathlib import Path

import requests

from ..config import env

API_BASE = "https://open.tiktokapis.com"
CHUNK_SIZE = 10 * 1024 * 1024   # 10 MB — TikTok requires 5–64 MB chunks


class TikTokError(RuntimeError):
    pass


class TikTokPoster:
    def __init__(self):
        self.client_key = env("TIKTOK_CLIENT_KEY", required=True)
        self.client_secret = env("TIKTOK_CLIENT_SECRET", required=True)
        self.access_token = env("TIKTOK_ACCESS_TOKEN", required=True)
        self.refresh_token = env("TIKTOK_REFRESH_TOKEN")

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def refresh(self) -> None:
        r = requests.post(
            f"{API_BASE}/v2/oauth/token/",
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        if "access_token" not in body:
            raise TikTokError(f"Refresh failed: {body}")
        self.access_token = body["access_token"]
        self.refresh_token = body.get("refresh_token", self.refresh_token)

    def post(
        self,
        video_path: Path,
        caption: str,
        privacy: str = "SELF_ONLY",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
    ) -> str:
        """Direct-post a video. Returns the publish_id."""
        size = video_path.stat().st_size
        chunk_size = min(CHUNK_SIZE, size)
        total_chunks = (size + chunk_size - 1) // chunk_size

        init_body = {
            "post_info": {
                "title": caption[:2200],
                "privacy_level": privacy,
                "disable_comment": disable_comment,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        }
        init = requests.post(
            f"{API_BASE}/v2/post/publish/video/init/",
            headers=self._auth_headers(),
            json=init_body,
            timeout=30,
        )
        if init.status_code == 401 and self.refresh_token:
            self.refresh()
            init = requests.post(
                f"{API_BASE}/v2/post/publish/video/init/",
                headers=self._auth_headers(),
                json=init_body,
                timeout=30,
            )
        init.raise_for_status()
        data = init.json()["data"]
        upload_url = data["upload_url"]
        publish_id = data["publish_id"]

        # Chunked upload via PUT with Content-Range
        with open(video_path, "rb") as f:
            for i in range(total_chunks):
                start = i * chunk_size
                buf = f.read(chunk_size)
                end = start + len(buf) - 1
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(buf)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                }
                up = requests.put(upload_url, data=buf, headers=headers, timeout=120)
                if up.status_code not in (200, 201, 206):
                    raise TikTokError(f"Chunk {i} upload failed: {up.status_code} {up.text}")

        return publish_id

    def status(self, publish_id: str) -> dict:
        r = requests.post(
            f"{API_BASE}/v2/post/publish/status/fetch/",
            headers=self._auth_headers(),
            json={"publish_id": publish_id},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()["data"]

    def wait_for_publish(self, publish_id: str, timeout: int = 300) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.status(publish_id)
            if s.get("status") in ("PUBLISH_COMPLETE", "PUBLISHED"):
                return s
            if s.get("status") == "FAILED":
                raise TikTokError(f"Publish failed: {s}")
            time.sleep(5)
        raise TikTokError(f"Timed out waiting for {publish_id}")
