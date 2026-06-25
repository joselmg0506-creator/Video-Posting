"""
Competitor-aware improvement suggestions — generated server-side once/day and cached.

For each enabled channel it:
  1. searches YouTube for the current top-performing Shorts in the channel's niche (OTHER
     creators), via the channel's own OAuth service (public read; ~100 quota units/search),
  2. summarizes the channel's own real metrics (live stats for its posted videos),
  3. asks Claude to compare the two and write 3 specific, grounded suggestions.

Writes data/suggestions.json. The dashboard bakes it in and shows it under "Ways to grow /
improve"; if the file is missing or a channel failed, the dashboard falls back to its built-in
client-side rules engine. Best-effort: any per-channel failure (quota, network, parse) is caught
so it never breaks the run — and it runs in the nightly metrics workflow, AFTER posting, so it
can never affect uploads.

  python main.py --suggestions
"""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import env

# Niche search query per channel (by name). Override with `niche:` on the channel in config.yaml.
_NICHE = {
    "clips": "kai cenat ishowspeed streamer clips funny moments",
    "stories": "minecraft parkour story time pov reddit",
    "characters": "italian brainrot shorts tralalero bombardiro",
}
_ACCENT = {"clips": "#3DDC97", "characters": "#FF6B5E", "stories": "#7C9CFF"}  # mirror dashboard palette


def _service(token_file: str):
    from .poster.youtube import YouTubeShortsPoster
    return YouTubeShortsPoster(token_file)._service


def _niche_top(svc, query: str, published_after: str, n: int = 12) -> list[dict]:
    """Top recent short videos in a niche: search.list (~100 units) + videos.list (1)."""
    r = svc.search().list(part="snippet", q=query, type="video", videoDuration="short",
                          order="viewCount", maxResults=n, regionCode="US",
                          relevanceLanguage="en", publishedAfter=published_after).execute()
    meta = {it["id"]["videoId"]: (it["snippet"]["title"], it["snippet"]["channelTitle"])
            for it in r.get("items", []) if it.get("id", {}).get("videoId")}
    out: list[dict] = []
    ids = list(meta)
    if ids:
        s = svc.videos().list(part="statistics", id=",".join(ids[:50])).execute()
        for it in s.get("items", []):
            t, ch = meta.get(it["id"], ("", ""))
            out.append({"title": t, "channel": ch,
                        "views": int(it.get("statistics", {}).get("viewCount", 0))})
    out.sort(key=lambda x: x["views"], reverse=True)
    return out


def _channel_rows(svc, posts: list[dict]) -> list[dict]:
    ids = [p["video_id"] for p in posts if p.get("video_id")]
    stats: dict = {}
    for i in range(0, len(ids), 50):
        s = svc.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
        for it in s.get("items", []):
            st = it.get("statistics", {})
            stats[it["id"]] = {
                "views": int(st.get("viewCount", 0)),
                "likes": int(st["likeCount"]) if "likeCount" in st else None,
                "comments": int(st["commentCount"]) if "commentCount" in st else None,
            }
    rows = []
    for p in posts:
        s = stats.get(p["video_id"], {})
        rows.append({"title": p.get("title", ""), "views": s.get("views", 0),
                     "likes": s.get("likes"), "comments": s.get("comments"),
                     "posted_at": p.get("posted_at", "")})
    return rows


def _age_days(iso: str) -> float:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400)
    except Exception:
        return 999.0


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0


def _extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def _ask_claude(client, model: str, name: str, niche: str, rows: list[dict], top: list[dict]) -> list[dict]:
    recent = sorted(rows, key=lambda r: r.get("posted_at", ""), reverse=True)[:15]
    posts_7d = sum(1 for r in rows if _age_days(r.get("posted_at", "")) <= 7)
    mine = "\n".join(
        f"- \"{(r['title'] or '')[:70]}\" — {r['views']} views"
        f"{', ' + str(r['likes']) + ' likes' if r['likes'] is not None else ''}"
        f"{', ' + str(r['comments']) + ' comments' if r['comments'] is not None else ''}"
        f" ({round(_age_days(r.get('posted_at','')))}d old)"
        for r in recent) or "- (no videos yet)"
    theirs = "\n".join(f"- \"{(t['title'] or '')[:70]}\" — {t['channel']} — {t['views']:,} views"
                       for t in top[:10]) or "- (no niche data available)"
    avg_mine = round(_mean([r["views"] for r in rows]))
    avg_top = round(_mean([t["views"] for t in top[:5]]))
    system = ("You are a sharp YouTube Shorts growth strategist. You give specific, honest, "
              "data-grounded advice by comparing a creator's real numbers to what's winning in "
              "their niche right now. No generic platitudes — cite concrete gaps, title patterns, "
              "and cadence. Be direct and encouraging.")
    user = f"""CHANNEL: "{name}" — niche: {niche}
Its recent Shorts (title — views — age):
{mine}
Its averages: ~{avg_mine:,} views/Short, {posts_7d} posted in the last 7 days.

TOP SHORTS RIGHT NOW from OTHER creators in this niche (title — channel — views):
{theirs}
Niche leaders average ~{avg_top:,} views on their top Shorts.

Compare this channel to the niche leaders and give EXACTLY 3 improvement suggestions. Each must
be grounded in BOTH the competitor data and this channel's own numbers (cite specifics — view
gaps, title/hook patterns the leaders use, posting cadence). Specific and doable, not generic.

Return ONLY a JSON array of exactly 3 objects, no prose:
[{{"tag":"<ONE WORD, UPPERCASE>","impact":"High|Med","title":"<5-7 word headline>","body":"<1-2 concrete sentences>"}}]"""
    msg = client.messages.create(model=model, max_tokens=900, system=system,
                                 messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    items = _extract_json(text)
    clean = []
    for it in items[:3]:
        if isinstance(it, dict) and it.get("title") and it.get("body"):
            clean.append({"tag": str(it.get("tag", "TIP"))[:12].upper(),
                          "impact": "High impact" if str(it.get("impact", "")).lower().startswith("h") else "Med impact",
                          "title": str(it["title"])[:60], "body": str(it["body"])[:240]})
    return clean


def generate(state, cfg: dict) -> Path:
    out_path = Path(cfg["paths"]["state"]).parent / "suggestions.json"
    key = env("ANTHROPIC_API_KEY")
    model = (cfg.get("transform", {}).get("llm", {}) or {}).get("model", "claude-haiku-4-5-20251001")
    if not key:
        print("  [suggestions] no ANTHROPIC_API_KEY — skipping (dashboard will use built-in tips)")
        return out_path
    from anthropic import Anthropic
    client = Anthropic(api_key=key)

    posts = [p for p in state.posts() if p.get("video_id")]
    by_ch: dict[str, list] = {}
    for p in posts:
        by_ch.setdefault(p.get("channel") or p.get("source") or "?", []).append(p)

    published_after = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    channels = [c for c in cfg.get("channels", []) if c.get("enabled")]

    result = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              "channels": {}, "global": [], "benchmarks": {}}

    for c in channels:
        name = c.get("name")
        niche = c.get("niche") or _NICHE.get(name) or f"{name} youtube shorts"
        try:
            svc = _service(c.get("token_file"))
            top = _niche_top(svc, niche, published_after)
            rows = _channel_rows(svc, by_ch.get(name, []))
            tips = _ask_claude(client, model, name, niche, rows, top)
            if tips:
                result["channels"][name] = tips
                result["global"].append({**tips[0], "channel": name})
            result["benchmarks"][name] = {
                "niche": niche,
                "your_avg": round(_mean([r["views"] for r in rows])),
                "niche_top_avg": round(_mean([t["views"] for t in top[:5]])),
                "top": top[:3],
            }
            print(f"  [suggestions] {name}: {len(tips)} tips (niche top avg "
                  f"{result['benchmarks'][name]['niche_top_avg']:,} vs your {result['benchmarks'][name]['your_avg']:,})")
        except Exception as e:
            print(f"  [suggestions] {name}: skipped ({type(e).__name__}: {e})")

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  suggestions -> {out_path}  ({len(result['channels'])} channels)")
    return out_path
