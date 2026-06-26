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
    meta = {it["id"]["videoId"]: (it["snippet"]["title"], it["snippet"]["channelTitle"],
                                  it["snippet"].get("publishedAt", ""), it["snippet"].get("channelId", ""))
            for it in r.get("items", []) if it.get("id", {}).get("videoId")}
    out: list[dict] = []
    ids = list(meta)
    if ids:
        s = svc.videos().list(part="statistics,contentDetails", id=",".join(ids[:50])).execute()
        for it in s.get("items", []):
            t, ch, pub, cid = meta.get(it["id"], ("", "", "", ""))
            out.append({"title": t, "channel": ch, "published": pub, "channel_id": cid,
                        "views": int(it.get("statistics", {}).get("viewCount", 0)),
                        "duration_s": _dur_seconds(it.get("contentDetails", {}).get("duration", ""))})
    out.sort(key=lambda x: x["views"], reverse=True)
    return out


def _channel_cadence(svc, channel_id: str):
    """Approx uploads/day for a channel from its recent uploads' publishedAt spacing (~2 quota)."""
    if not channel_id:
        return None
    try:
        ch = svc.channels().list(part="contentDetails", id=channel_id).execute().get("items", [])
        if not ch:
            return None
        uploads = ch[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = svc.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=25).execute()
        dates = sorted(it["contentDetails"]["videoPublishedAt"] for it in pl.get("items", [])
                       if it.get("contentDetails", {}).get("videoPublishedAt"))
        if len(dates) < 3:
            return None
        t0 = datetime.fromisoformat(dates[0].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))
        days = max(0.5, (t1 - t0).total_seconds() / 86400)
        return round((len(dates) - 1) / days, 1)
    except Exception:
        return None


def _channel_rows(svc, posts: list[dict]) -> list[dict]:
    ids = [p["video_id"] for p in posts if p.get("video_id")]
    stats: dict = {}
    for i in range(0, len(ids), 50):
        s = svc.videos().list(part="statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        for it in s.get("items", []):
            st = it.get("statistics", {})
            stats[it["id"]] = {
                "views": int(st.get("viewCount", 0)),
                "likes": int(st["likeCount"]) if "likeCount" in st else None,
                "comments": int(st["commentCount"]) if "commentCount" in st else None,
                "duration_s": _dur_seconds(it.get("contentDetails", {}).get("duration", "")),
            }
    rows = []
    for p in posts:
        s = stats.get(p["video_id"], {})
        rows.append({"title": p.get("title", ""), "views": s.get("views", 0),
                     "likes": s.get("likes"), "comments": s.get("comments"),
                     "duration_s": s.get("duration_s", 0), "posted_at": p.get("posted_at", "")})
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


def _hour_central(iso: str):
    """ISO-8601 timestamp -> hour of day in US Central (Texas). CDT (UTC-5) — close enough as a
    posting-time signal (winter CST would shift 1h)."""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (t.hour - 5) % 24
    except Exception:
        return None


def _dur_seconds(iso: str) -> int:
    """ISO-8601 duration (PT#M#S) -> seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mn * 60 + s


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⬀-⯿✨❤]")


def _title_stats(titles: list[str]) -> dict:
    """Structured title/hook patterns across a set of titles (for leaders-vs-us benchmarking)."""
    titles = [t for t in titles if t]
    n = len(titles)
    if not n:
        return {"n": 0}

    def has_caps(t):
        return any(len(w) >= 2 and w.isupper() for w in re.findall(r"[A-Za-z]+", t))

    return {
        "n": n,
        "avg_words": round(_mean([len(t.split()) for t in titles]), 1),
        "emoji_pct": round(100 * sum(1 for t in titles if _EMOJI.search(t)) / n),
        "caps_pct": round(100 * sum(1 for t in titles if has_caps(t)) / n),
        "num_pct": round(100 * sum(1 for t in titles if re.search(r"\d", t)) / n),
        "question_pct": round(100 * sum(1 for t in titles if "?" in t) / n),
    }


def _extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def _ask_claude(client, model: str, name: str, niche: str, rows: list[dict], top: list[dict],
                compare: dict | None = None) -> list[dict]:
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
    c = compare or {}
    ls, oss, ld = c.get("titles", {}).get("leaders", {}), c.get("titles", {}).get("yours", {}), c.get("length_s", {})
    cmp_txt = ""
    if ls.get("n") and oss.get("n"):
        cmp_txt += (f"\nTITLE PATTERNS (niche leaders vs you):\n"
                    f"- words per title: {ls['avg_words']} vs {oss['avg_words']}\n"
                    f"- uses an emoji: {ls['emoji_pct']}% vs {oss['emoji_pct']}%\n"
                    f"- has an ALL-CAPS word: {ls['caps_pct']}% vs {oss['caps_pct']}%\n"
                    f"- has a number: {ls['num_pct']}% vs {oss['num_pct']}%\n"
                    f"- is a question: {ls['question_pct']}% vs {oss['question_pct']}%")
    if ld.get("leaders"):
        cmp_txt += f"\nVIDEO LENGTH: leaders average ~{ld['leaders']}s vs you ~{ld.get('yours', 0)}s"
    tm = c.get("timing", {})
    ot, nt = tm.get("ours", {}), tm.get("niche_hours", {})
    if ot:
        slots = ", ".join(f"{h}:00->{v['avg']} views" for h, v in sorted(ot.items()))
        cmp_txt += f"\nYOUR POSTING SLOTS (US Central -> avg views/Short): {slots}"
    if nt:
        topn = sorted(nt.items(), key=lambda kv: -kv[1])[:3]
        cmp_txt += "\nNICHE leaders' top Shorts were posted mostly around (US Central): " + \
                   ", ".join(f"{h}:00" for h, _ in topn)
    cad = c.get("cadence", {})
    if cad.get("leaders_per_day"):
        cmp_txt += (f"\nPOSTING CADENCE: niche leaders upload ~{cad['leaders_per_day']} Shorts/day "
                    f"vs you ~{cad.get('yours_per_day', 0)}/day")
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
{cmp_txt}

Compare this channel to the niche leaders and give EXACTLY 3 improvement suggestions. Each must
be grounded in BOTH the competitor data and this channel's own numbers — CITE the concrete
gaps above across title patterns, length, AND POSTING TIME (e.g. "leaders use emojis in 80% of
titles, you 0%"; "leaders' Shorts run ~25s, yours ~45s"; "your 8pm slot gets 5x the views of
your noon slot — drop the noon post"). Specific and doable, not generic.

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
            from collections import defaultdict
            oh = defaultdict(lambda: [0, 0])                 # our posting hour -> [count, sum_views]
            for r in rows:
                h = _hour_central(r.get("posted_at", ""))
                if h is not None:
                    oh[h][0] += 1
                    oh[h][1] += r.get("views", 0)
            nh = defaultdict(int)                            # niche leaders' posting hour -> count
            for t in top[:12]:
                h = _hour_central(t.get("published", ""))
                if h is not None:
                    nh[h] += 1
            seen_ch, cads = [], []                           # niche leaders' upload cadence (per day)
            for t in top:
                cid = t.get("channel_id")
                if cid and cid not in seen_ch:
                    seen_ch.append(cid)
                    cd = _channel_cadence(svc, cid)
                    if cd:
                        cads.append(cd)
                if len(seen_ch) >= 4:
                    break
            our_7d = sum(1 for r in rows if _age_days(r.get("posted_at", "")) <= 7)
            compare = {
                "titles": {"leaders": _title_stats([t["title"] for t in top[:12]]),
                           "yours": _title_stats([r["title"] for r in rows])},
                "length_s": {"leaders": round(_mean([t["duration_s"] for t in top[:10] if t.get("duration_s")])),
                             "yours": round(_mean([r["duration_s"] for r in rows if r.get("duration_s")]))},
                "timing": {"ours": {h: {"n": c, "avg": round(v / c)} for h, (c, v) in oh.items() if c},
                           "niche_hours": dict(nh)},
                "cadence": {"leaders_per_day": round(_mean(cads), 1) if cads else 0,
                            "yours_per_day": round(our_7d / 7, 1), "samples": cads},
            }
            tips = _ask_claude(client, model, name, niche, rows, top, compare)
            if tips:
                result["channels"][name] = tips
                result["global"].append({**tips[0], "channel": name})
            result["benchmarks"][name] = {
                "niche": niche,
                "your_avg": round(_mean([r["views"] for r in rows])),
                "niche_top_avg": round(_mean([t["views"] for t in top[:5]])),
                "top": top[:3],
                "compare": compare,
            }
            print(f"  [suggestions] {name}: {len(tips)} tips (niche top avg "
                  f"{result['benchmarks'][name]['niche_top_avg']:,} vs your {result['benchmarks'][name]['your_avg']:,})")
        except Exception as e:
            print(f"  [suggestions] {name}: skipped ({type(e).__name__}: {e})")

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  suggestions -> {out_path}  ({len(result['channels'])} channels)")
    return out_path
