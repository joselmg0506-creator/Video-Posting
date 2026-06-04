import json
from pathlib import Path


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {}
        self.data.setdefault("posted", [])   # clip ids, for dedup
        self.data.setdefault("posts", [])    # rich records, for metrics

    def is_posted(self, clip_id: str) -> bool:
        return clip_id in self.data["posted"]

    def mark_posted(self, clip_id: str) -> None:
        if clip_id not in self.data["posted"]:
            self.data["posted"].append(clip_id)
            self._save()

    def record_post(self, clip_id: str, **info) -> None:
        """Mark posted (dedup) AND store a rich record for the metrics digest."""
        if clip_id not in self.data["posted"]:
            self.data["posted"].append(clip_id)
        self.data["posts"].append({"clip_id": clip_id, **info})
        self._save()

    def posts(self) -> list[dict]:
        return self.data.get("posts", [])

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
