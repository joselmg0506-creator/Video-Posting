"""
Quick self-contained HTML analytics dashboard across ALL channels.

Reads posted records from state.json, pulls live view/like/comment counts from YouTube (per
channel, using that channel's own token so even private videos are included), and writes one
dark-themed HTML file you can open in a browser.

  python main.py --dashboard          # build data/dashboard.html and open it
  python main.py --dashboard --no-open # just build it
"""
import html
from datetime import datetime, timezone
from pathlib import Path


def _token_map(cfg: dict) -> dict:
    return {c["name"]: c.get("token_file") for c in cfg.get("channels", [])}


def _fetch_stats(token_file: str, video_ids: list[str]) -> dict:
    """videos.list(statistics) for one channel's videos, batched by 50."""
    if not token_file or not video_ids:
        return {}
    from .poster.youtube import YouTubeShortsPoster
    try:
        svc = YouTubeShortsPoster(token_file)._service
    except Exception as e:
        print(f"  [dashboard] {token_file}: {e}")
        return {}
    out: dict = {}
    for i in range(0, len(video_ids), 50):
        try:
            r = svc.videos().list(part="statistics", id=",".join(video_ids[i:i + 50])).execute()
            for it in r.get("items", []):
                s = it.get("statistics", {})
                out[it["id"]] = {
                    "views": int(s.get("viewCount", 0)),
                    "likes": int(s.get("likeCount", 0)),
                    "comments": int(s.get("commentCount", 0)),
                }
        except Exception as e:
            print(f"  [dashboard] stats fetch failed: {e}")
    return out


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def build(state, cfg: dict, open_after: bool = True) -> Path:
    posts = [p for p in state.posts() if p.get("video_id")]
    tokmap = _token_map(cfg)

    by_channel: dict[str, list] = {}
    for p in posts:
        by_channel.setdefault(p.get("channel") or p.get("source") or "?", []).append(p)

    stats: dict = {}
    for ch, plist in by_channel.items():
        stats.update(_fetch_stats(tokmap.get(ch), [p["video_id"] for p in plist]))

    def s(p):
        return stats.get(p["video_id"], {"views": 0, "likes": 0, "comments": 0})

    # per-channel aggregates
    cards = []
    for ch in sorted(by_channel, key=lambda c: sum(s(p)["views"] for p in by_channel[c]), reverse=True):
        pl = by_channel[ch]
        v = sum(s(p)["views"] for p in pl)
        lk = sum(s(p)["likes"] for p in pl)
        cm = sum(s(p)["comments"] for p in pl)
        cards.append((ch, len(pl), v, lk, cm))

    tot_v = sum(c[2] for c in cards)
    tot_l = sum(c[3] for c in cards)
    tot_c = sum(c[4] for c in cards)

    # rows, newest first
    rows = sorted(posts, key=lambda p: p.get("posted_at", ""), reverse=True)

    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    card_html = "".join(
        f'<div class="card"><div class="ch">{html.escape(c[0])}</div>'
        f'<div class="big">{_fmt(c[2])}</div><div class="lbl">views</div>'
        f'<div class="sub">{c[1]} videos · {_fmt(c[3])} likes · {_fmt(c[4])} comments</div></div>'
        for c in cards
    ) or '<div class="card"><div class="sub">No posts yet — the dashboard fills in as videos go up.</div></div>'

    row_html = "".join(
        f'<tr><td class="t"><a href="{html.escape(p.get("url",""))}" target="_blank">{html.escape((p.get("title") or "")[:70])}</a></td>'
        f'<td>{html.escape(p.get("channel") or p.get("source") or "?")}</td>'
        f'<td class="n">{_fmt(s(p)["views"])}</td>'
        f'<td class="n">{_fmt(s(p)["likes"])}</td>'
        f'<td class="n">{_fmt(s(p)["comments"])}</td>'
        f'<td class="d">{html.escape((p.get("posted_at") or "")[:10])}</td></tr>'
        for p in rows
    )

    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>VideoPOsting — Analytics</title>
<style>
 body{{background:#0d1117;color:#e6edf3;font-family:Segoe UI,system-ui,Arial,sans-serif;margin:0;padding:24px}}
 h1{{margin:0 0 4px;font-size:22px}} .gen{{color:#8b949e;font-size:13px;margin-bottom:20px}}
 .totals{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
 .tot{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px 22px;min-width:120px}}
 .tot .big{{font-size:28px;font-weight:700}} .tot .lbl{{color:#8b949e;font-size:13px}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px}}
 .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px 20px;min-width:200px}}
 .card .ch{{color:#58a6ff;font-weight:600;margin-bottom:8px}} .card .big{{font-size:26px;font-weight:700}}
 .card .lbl{{color:#8b949e;font-size:12px}} .card .sub{{color:#8b949e;font-size:12px;margin-top:8px}}
 table{{width:100%;border-collapse:collapse;background:#161b22;border-radius:12px;overflow:hidden}}
 th,td{{text-align:left;padding:10px 14px;border-bottom:1px solid #21262d;font-size:14px}}
 th{{color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase}}
 td.n{{text-align:right;font-variant-numeric:tabular-nums}} td.d{{color:#8b949e}}
 a{{color:#58a6ff;text-decoration:none}} a:hover{{text-decoration:underline}}
 .t{{max-width:420px}}
</style></head><body>
<h1>📊 VideoPOsting Analytics</h1>
<div class="gen">generated {gen} · refresh by re-running the dashboard</div>
<div class="totals">
 <div class="tot"><div class="big">{len(cards) if posts else 0}</div><div class="lbl">channels</div></div>
 <div class="tot"><div class="big">{len(posts)}</div><div class="lbl">videos posted</div></div>
 <div class="tot"><div class="big">{_fmt(tot_v)}</div><div class="lbl">total views</div></div>
 <div class="tot"><div class="big">{_fmt(tot_l)}</div><div class="lbl">total likes</div></div>
 <div class="tot"><div class="big">{_fmt(tot_c)}</div><div class="lbl">total comments</div></div>
</div>
<div class="cards">{card_html}</div>
<table><thead><tr><th>Video</th><th>Channel</th><th>Views</th><th>Likes</th><th>Comments</th><th>Posted</th></tr></thead>
<tbody>{row_html}</tbody></table>
</body></html>"""

    out = Path(cfg["paths"]["state"]).parent / "dashboard.html"
    out.write_text(page, encoding="utf-8")
    print(f"  dashboard -> {out}  ({len(posts)} videos, {_fmt(tot_v)} views)")
    if open_after:
        import os
        try:
            os.startfile(str(out))   # opens in default browser on Windows
        except Exception:
            pass
    return out
