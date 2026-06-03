import json
from pathlib import Path


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"posted": []}

    def is_posted(self, clip_id: str) -> bool:
        return clip_id in self.data["posted"]

    def mark_posted(self, clip_id: str) -> None:
        if clip_id not in self.data["posted"]:
            self.data["posted"].append(clip_id)
            self._save()

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
