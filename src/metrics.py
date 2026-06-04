"""
Daily metrics digest — pulls view/like/comment stats for recently posted videos via the
YouTube Data API and reports a leaderboard plus per-creator and narrated-vs-raw averages
(the actionable part: learn what works and double down). Prints to console and, if a
Discord webhook is configured, posts the same digest there.

Run it with `python main.py --metrics` (or on a daily schedule).
"""
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from .poster.youtube import _load_credentials
from . import notify


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

    lines = [
        f"📊 **Daily digest** — {len(rows)} Shorts in the last {hours}h",
        f"**{tv:,}** views · {tl:,} likes · {tc:,} comments",
        "",
        "🏆 Top:",
    ]
    for i, r in enumerate(rows[:5], 1):
        lines.append(f"{i}. {str(r.get('title', '?'))[:50]} — {r['views']:,} views ({r.get('creator', '?')})")

    by_creator = _avg_by(rows, "creator")
    lines.append("")
    lines.append("By creator (avg views): " +
                 " · ".join(f"{k} {int(v):,}" for k, v in sorted(by_creator.items(), key=lambda x: -x[1])))

    narr = {"narrated": [], "raw": []}
    for r in rows:
        narr["narrated" if r.get("narrated") else "raw"].append(r["views"])
    fmt = [f"{k} {int(sum(v) / len(v)):,}" for k, v in narr.items() if v]
    lines.append("By format (avg views): " + " · ".join(fmt))

    msg = "\n".join(lines)
    print(msg)
    notify.send(content=msg, enabled=notif_on)
    return msg
