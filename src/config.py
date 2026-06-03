import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path = "config.yaml") -> dict:
    with open(ROOT / path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("downloads", "processed"):
        Path(cfg["paths"][key]).mkdir(parents=True, exist_ok=True)
    Path(cfg["paths"]["state"]).parent.mkdir(parents=True, exist_ok=True)
    return cfg


def env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val
