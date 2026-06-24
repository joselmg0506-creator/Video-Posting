import json
import os
from pathlib import Path


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {}
        self.data.setdefault("posted", [])      # clip ids, for dedup
        self.data.setdefault("uploading", [])   # clip ids mid-upload, for crash-safety
        self.data.setdefault("posts", [])       # rich records, for metrics

    def is_posted(self, clip_id: str) -> bool:
        return clip_id in self.data["posted"]

    def is_pending(self, clip_id: str) -> bool:
        """True if an upload was started but never confirmed — i.e. a previous run
        crashed mid-upload. Such clips are skipped (not blindly re-uploaded) until a
        human clears them, so a retry can't double-post."""
        return clip_id in self.data["uploading"] and clip_id not in self.data["posted"]

    def begin(self, clip_id: str) -> None:
        """Mark an upload as in-progress BEFORE calling the platform API, so an
        interrupted run leaves a durable trace instead of silently re-uploading."""
        if clip_id not in self.data["uploading"]:
            self.data["uploading"].append(clip_id)
            self._save()

    def clear_pending(self, clip_id: str) -> None:
        """Drop the in-progress marker when we KNOW the upload didn't happen
        (e.g. the API rejected the request before any bytes were sent)."""
        if clip_id in self.data["uploading"]:
            self.data["uploading"].remove(clip_id)
            self._save()

    def mark_posted(self, clip_id: str) -> None:
        if clip_id not in self.data["posted"]:
            self.data["posted"].append(clip_id)
        if clip_id in self.data["uploading"]:
            self.data["uploading"].remove(clip_id)
        self._save()

    def record_post(self, clip_id: str, **info) -> None:
        """Confirm a successful post: dedup-mark posted, clear the in-progress marker,
        and store ONE rich record per clip_id for the metrics digest (re-recording the
        same clip won't append a duplicate row that would skew the stats)."""
        if clip_id not in self.data["posted"]:
            self.data["posted"].append(clip_id)
        if clip_id in self.data["uploading"]:
            self.data["uploading"].remove(clip_id)
        if not any(p.get("clip_id") == clip_id for p in self.data["posts"]):
            self.data["posts"].append({"clip_id": clip_id, **info})
        self._save()

    def posts(self) -> list[dict]:
        return self.data.get("posts", [])

    def _save(self) -> None:
        """Atomic write: serialize to a temp file in the same dir then os.replace (atomic
        on Windows + POSIX), so a crash mid-write — or two overlapping runs — can't leave
        a half-written/corrupt state.json."""
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
