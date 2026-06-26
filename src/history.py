"""
Daily view/like/comment snapshots -> data/history.json, for REAL day-over-day trends.

Run once a day (`python main.py --snapshot`, wired into the nightly metrics workflow). It appends
one row per posted video per day; the dashboard then plots true daily growth from this instead of
faking the trend from publish dates. Best-effort: a per-channel fetch failure is skipped, never
fatal. The file is git-tracked (like state.json) so the cloud accumulates history across runs.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

KEEP_DAYS = 120   # cap history so the committed file stays small (~a few hundred KB at most)


def _token_map(cfg: dict) -> dict:
    return {c["name"]: c.get("token_file") for c in cfg.get("channels", [])}


def _fetch(token_file: str, ids: list[str]) -> dict:
    if not token_file or not ids:
        return {}
    from .poster.youtube import YouTubeShortsPoster
    try:
        svc = YouTubeShortsPoster(token_file)._service
    except Exception as e:
        print(f"  [history] {token_file}: {e}")
        return {}
    out: dict = {}
    for i in range(0, len(ids), 50):
        try:
            r = svc.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
            for it in r.get("items", []):
                s = it.get("statistics", {})
                out[it["id"]] = (int(s.get("viewCount", 0)),
                                 int(s["likeCount"]) if "likeCount" in s else None,
                                 int(s["commentCount"]) if "commentCount" in s else None)
        except Exception as e:
            print(f"  [history] fetch failed: {e}")
    return out


def snapshot(state, cfg: dict) -> Path:
    path = Path(cfg["paths"]["state"]).parent / "history.json"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    posts = [p for p in state.posts() if p.get("video_id")]
    by_ch: dict[str, list] = {}
    for p in posts:
        by_ch.setdefault(p.get("channel") or p.get("source") or "?", []).append(p)

    tok = _token_map(cfg)
    rows: list[dict] = []
    for ch, plist in by_ch.items():
        stats = _fetch(tok.get(ch), [p["video_id"] for p in plist])
        for p in plist:
            s = stats.get(p["video_id"])
            if s:
                rows.append({"date": today, "id": p["video_id"], "channel": ch,
                             "views": s[0], "likes": s[1], "comments": s[2]})

    try:
        hist = json.loads(path.read_text(encoding="utf-8")).get("rows", []) if path.exists() else []
    except Exception:
        hist = []
    hist = [r for r in hist if r.get("date") != today]   # re-snapshot today (don't duplicate)
    hist += rows

    dates = sorted({r["date"] for r in hist})
    if len(dates) > KEEP_DAYS:                            # prune oldest days
        keep = set(dates[-KEEP_DAYS:])
        hist = [r for r in hist if r["date"] in keep]

    path.write_text(json.dumps({"updated": today, "rows": hist}, indent=2), encoding="utf-8")
    print(f"  history -> {path}  ({len(rows)} videos today, {len(set(r['date'] for r in hist))} day(s) total)")
    return path
