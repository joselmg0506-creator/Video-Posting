"""
Daily metrics digest — pulls view/like/comment stats for recently posted videos via the
YouTube Data API and reports a leaderboard plus per-creator and narrated-vs-raw averages
(the actionable part: learn what works and double down). Prints to console and, if a
Discord webhook is configured, posts the same digest there.

Run it with `python main.py --metrics` (or on a daily schedule).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build

from .poster.youtube import _load_credentials
from . import notify


def _when_label(hours: int) -> str:
    return f"{datetime.now().strftime('%b %d, %Y')} · last {hours}h"


def _parse(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _recent(posts: list[dict], hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for p in posts:
        if not p.get("video_id"):
            continue
        t = _parse(p.get("posted_at", ""))
        if t is None or t >= cutoff:
            out.append(p)
    return out


def fetch_stats(video_ids: list[str]) -> dict[str, dict]:
    svc = build("youtube", "v3", credentials=_load_credentials())
    stats: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        resp = svc.videos().list(part="statistics", id=",".join(video_ids[i:i + 50])).execute()
        for item in resp.get("items", []):
            s = item.get("statistics", {})
            stats[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            }
    return stats


def _avg_by(rows: list[dict], key: str) -> dict[str, float]:
    groups: dict[str, list[int]] = {}
    for r in rows:
        groups.setdefault(str(r.get(key) or "?"), []).append(r["views"])
    return {k: sum(v) / len(v) for k, v in groups.items()}


def digest(state, cfg: dict, hours: int = 24) -> str:
    notif_on = cfg.get("notifications", {}).get("discord", {}).get("enabled", False)
    posts = _recent(state.posts(), hours)
    if not posts:
        msg = f"📊 Daily digest — no posts in the last {hours}h."
        print(msg)
        notify.send(content=msg, enabled=notif_on)
        return msg

    stats = fetch_stats([p["video_id"] for p in posts])
    rows = [{**p, **stats.get(p["video_id"], {"views": 0, "likes": 0, "comments": 0})} for p in posts]
    rows.sort(key=lambda r: r["views"], reverse=True)

    tv = sum(r["views"] for r in rows)
    tl = sum(r["likes"] for r in rows)
    tc = sum(r["comments"] for r in rows)
    by_creator = _avg_by(rows, "creator")
    narr = {"narrated": [], "raw": []}
    for r in rows:
        narr["narrated" if r.get("narrated") else "raw"].append(r["views"])
    by_format = {k: (sum(v) / len(v) if v else None) for k, v in narr.items()}

    top_line = " | ".join(f"{str(r.get('title', '?'))[:30]} {r['views']:,}" for r in rows[:3])
    print(f"📊 {len(rows)} Shorts · {tv:,} views · {tl:,} likes · {tc:,} comments | top: {top_line}")

    label = _when_label(hours)
    sd = {
        "when": label,
        "totals": {"views": tv, "likes": tl, "comments": tc, "count": len(rows)},
        "top": [{"title": str(r.get("title", "?")), "views": r["views"],
                 "creator": str(r.get("creator", "?"))} for r in rows],
        "by_creator": by_creator,
        "by_format": by_format,
    }
    try:
        from . import dashboard
        png = Path(cfg["paths"]["state"]).parent / "dashboard.png"
        dashboard.render(sd, png)
        notify.send_file(png, content=f"📊 **Daily Dashboard** — {label}", enabled=notif_on)
    except Exception as e:
        print(f"  [dashboard] skipped ({e}); sending text")
        notify.send(content=f"📊 {len(rows)} Shorts · {tv:,} views · top: {top_line}", enabled=notif_on)
    return "ok"
