"""
Self-contained, mobile-first HTML analytics dashboard across ALL channels.

How it stays fresh: the page renders its numbers **client-side in the browser**. On every
load (and when you switch back to the tab, and every 2 min while open) it calls the YouTube
Data API for the current view/like/comment counts — so a simple refresh shows live numbers
instead of whatever was baked in at build time.

That live fetch needs a YouTube Data API key in env var `YT_API_KEY` (a browser key restricted
to your Pages domain). The key is injected into the page at build time. If it's missing, the
page still works — it shows the counts baked in at build time (fetched server-side via each
channel's OAuth token) and a small banner explaining how to turn live updates on.

  python main.py --dashboard          # build data/dashboard.html and open it
  python main.py --dashboard --no-open # just build it
"""
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import env


def _token_map(cfg: dict) -> dict:
    return {c["name"]: c.get("token_file") for c in cfg.get("channels", [])}


def _fetch_stats(token_file: str, video_ids: list[str]) -> dict:
    """videos.list(statistics) for one channel's videos, batched by 50.

    Used only for the build-time fallback numbers (the live values come from the browser).
    """
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


# distinct accent per channel (reused for cards, left-borders and chips)
_PALETTE = ["#58a6ff", "#3fb950", "#bc8cff", "#f0883e", "#f778ba", "#39c5cf", "#e3b341"]


def _safe(j: str) -> str:
    """Make a JSON blob safe to drop inside a <script> tag."""
    return j.replace("</", "<\\/")


def build(state, cfg: dict, open_after: bool = True) -> Path:
    posts = [p for p in state.posts() if p.get("video_id")]

    by_channel: dict[str, list] = {}
    for p in posts:
        by_channel.setdefault(p.get("channel") or p.get("source") or "?", []).append(p)

    tokmap = _token_map(cfg)
    stats: dict = {}
    for ch, plist in by_channel.items():
        stats.update(_fetch_stats(tokmap.get(ch), [p["video_id"] for p in plist]))

    def s(p):
        return stats.get(p["video_id"], {"views": 0, "likes": 0, "comments": 0})

    rows = sorted(posts, key=lambda p: p.get("posted_at", ""), reverse=True)
    posts_json = [{
        "id": p["video_id"],
        "title": (p.get("title") or "")[:120],
        "channel": p.get("channel") or p.get("source") or "?",
        "url": p.get("url") or f"https://youtube.com/shorts/{p['video_id']}",
        "date": (p.get("posted_at") or "")[:10],
        "views": s(p)["views"], "likes": s(p)["likes"], "comments": s(p)["comments"],
    } for p in rows]

    channel_names = sorted({pj["channel"] for pj in posts_json})
    channels = {name: _PALETTE[i % len(_PALETTE)] for i, name in enumerate(channel_names)}

    api_key = env("YT_API_KEY", "") or ""
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    page = (_TEMPLATE
            .replace("__POSTS__", _safe(json.dumps(posts_json)))
            .replace("__CHANNELS__", _safe(json.dumps(channels)))
            .replace("__APIKEY__", json.dumps(api_key))
            .replace("__GEN__", html.escape(gen)))

    out = Path(cfg["paths"]["state"]).parent / "dashboard.html"
    out.write_text(page, encoding="utf-8")
    live = "live (YT_API_KEY set)" if api_key else "build-time numbers (no YT_API_KEY)"
    print(f"  dashboard -> {out}  ({len(posts)} videos, {live})")
    if open_after:
        import os
        try:
            os.startfile(str(out))   # opens in default browser on Windows
        except Exception:
            pass
    return out


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0d1117">
<title>VideoPOsting — Analytics</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--card2:#1b222c;--bd:#30363d;--mut:#8b949e;--tx:#e6edf3}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--tx);margin:0;padding:16px;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,Arial,sans-serif;
 -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
.wrap{max-width:920px;margin:0 auto}
header{display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap}
h1{font-size:21px;margin:0;letter-spacing:-.01em}
.status{font-size:12px;color:var(--mut)}
.status .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#3fb950;
 margin-right:5px;vertical-align:middle;box-shadow:0 0 0 0 rgba(63,185,80,.6);animation:p 2s infinite}
@keyframes p{0%{box-shadow:0 0 0 0 rgba(63,185,80,.5)}70%{box-shadow:0 0 0 6px rgba(63,185,80,0)}100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
#banner:not(:empty){background:#1f2530;border:1px solid var(--bd);color:var(--mut);
 font-size:12.5px;line-height:1.5;border-radius:10px;padding:10px 13px;margin:12px 0}
#banner b{color:var(--tx)}
.totals{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:14px 0}
.tot{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:13px 15px}
.tot .big{font-size:23px;font-weight:750;font-variant-numeric:tabular-nums}
.tot .lbl{color:var(--mut);font-size:12px;margin-top:1px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:24px 2px 11px;font-weight:650}
.chcards{display:grid;grid-template-columns:1fr;gap:10px}
.chcard{background:var(--card);border:1px solid var(--bd);border-left:4px solid #58a6ff;border-radius:14px;padding:13px 16px}
.chcard .ch{font-weight:700;margin-bottom:5px}
.chcard .big{font-size:21px;font-weight:750;font-variant-numeric:tabular-nums}
.chcard .big span{font-size:12px;font-weight:500;color:var(--mut)}
.chcard .sub{color:var(--mut);font-size:12.5px;margin-top:5px}
.vids{display:grid;grid-template-columns:1fr;gap:10px}
.vid{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:13px 15px;
 display:block;text-decoration:none;color:inherit;transition:background .12s,border-color .12s}
.vid:hover{background:var(--card2);border-color:#3d444d}
.vid .vt{font-weight:600;font-size:15px;line-height:1.35;margin-bottom:9px;display:flex;gap:8px;align-items:flex-start}
.vid .vt span:first-child{flex:1}
.chip{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;
 padding:3px 8px;border-radius:999px;white-space:nowrap;flex:none;margin-top:1px}
.vid .row{display:flex;gap:15px;color:var(--mut);font-size:13px;align-items:center;flex-wrap:wrap}
.vid .row b{color:var(--tx);font-variant-numeric:tabular-nums;font-weight:650}
.vid .date{margin-left:auto;font-size:12px}
.empty{color:var(--mut);font-size:14px;padding:26px 16px;text-align:center;
 background:var(--card);border:1px dashed var(--bd);border-radius:14px}
.foot{margin-top:20px;font-size:11.5px;color:var(--mut);text-align:center}
@media(min-width:700px){
 body{padding:28px}
 h1{font-size:25px}
 .totals{grid-template-columns:repeat(5,1fr)}
 .tot .big{font-size:26px}
 .chcards{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
}
</style></head><body><div class="wrap">
<header><h1>📊 VideoPOsting</h1><div class="status" id="status">…</div></header>
<div id="banner"></div>
<div class="totals" id="totals"></div>
<h2>Channels</h2><div class="chcards" id="chcards"></div>
<h2>Recent videos</h2><div class="vids" id="vids"></div>
<div class="foot">built __GEN__ · numbers refresh live in your browser</div>
</div>
<script>
const POSTS = __POSTS__;
const CHANNELS = __CHANNELS__;
const API_KEY = __APIKEY__;

function fmt(n){n=+n||0;if(n>=1e6)return(n/1e6).toFixed(1).replace(/\.0$/,'')+'M';
 if(n>=1e3)return(n/1e3).toFixed(1).replace(/\.0$/,'')+'K';return''+n;}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
function color(ch){return CHANNELS[ch]||'#58a6ff';}

function render(){
 const chans=[...new Set(POSTS.map(p=>p.channel))];
 const tv=POSTS.reduce((a,p)=>a+(+p.views||0),0);
 const tl=POSTS.reduce((a,p)=>a+(+p.likes||0),0);
 const tc=POSTS.reduce((a,p)=>a+(+p.comments||0),0);
 document.getElementById('totals').innerHTML=[
  [chans.length,'channels'],[POSTS.length,'videos'],[fmt(tv),'views'],[fmt(tl),'likes'],[fmt(tc),'comments']
 ].map(t=>'<div class="tot"><div class="big">'+t[0]+'</div><div class="lbl">'+t[1]+'</div></div>').join('');

 const agg={};
 POSTS.forEach(p=>{const a=agg[p.channel]||(agg[p.channel]={n:0,v:0,l:0,c:0});a.n++;a.v+=+p.views||0;a.l+=+p.likes||0;a.c+=+p.comments||0;});
 const cards=Object.entries(agg).sort((a,b)=>b[1].v-a[1].v).map(function(e){const ch=e[0],a=e[1],c=color(ch);
  return '<div class="chcard" style="border-left-color:'+c+'">'+
   '<div class="ch" style="color:'+c+'">'+esc(ch)+'</div>'+
   '<div class="big">'+fmt(a.v)+' <span>views</span></div>'+
   '<div class="sub">'+a.n+' videos · '+fmt(a.l)+' likes · '+fmt(a.c)+' comments</div></div>';}).join('');
 document.getElementById('chcards').innerHTML=cards||'<div class="empty">No posts yet.</div>';

 const vids=POSTS.map(function(p){const c=color(p.channel);
  return '<a class="vid" href="'+esc(p.url)+'" target="_blank" rel="noopener">'+
   '<div class="vt"><span>'+esc(p.title||'(untitled)')+'</span>'+
   '<span class="chip" style="background:'+c+'22;color:'+c+'">'+esc(p.channel)+'</span></div>'+
   '<div class="row"><span><b>'+fmt(p.views)+'</b> views</span>'+
   '<span><b>'+fmt(p.likes)+'</b> likes</span>'+
   '<span><b>'+fmt(p.comments)+'</b> comments</span>'+
   '<span class="date">'+esc(p.date)+'</span></div></a>';}).join('');
 document.getElementById('vids').innerHTML=vids||'<div class="empty">No videos posted yet — this fills in as Shorts go up.</div>';
}

function setStatus(txt,live){document.getElementById('status').innerHTML=(live?'<span class="dot"></span>':'')+esc(txt);}

async function refresh(){
 if(!API_KEY){
  document.getElementById('banner').innerHTML='⚡ Live updates are off. Add a YouTube Data API key as the GitHub secret <b>YT_API_KEY</b> (restricted to this domain) to see real-time numbers on every refresh. Showing the last build for now.';
  setStatus('last build',false);return;
 }
 const ids=[...new Set(POSTS.map(p=>p.id).filter(Boolean))];
 if(!ids.length){setStatus('no videos yet',false);return;}
 setStatus('updating…',false);
 try{
  const byId={};
  for(let i=0;i<ids.length;i+=50){
   const batch=ids.slice(i,i+50);
   const r=await fetch('https://www.googleapis.com/youtube/v3/videos?part=statistics&id='+batch.join(',')+'&key='+API_KEY);
   if(!r.ok)throw new Error('HTTP '+r.status);
   const j=await r.json();
   (j.items||[]).forEach(it=>{const s=it.statistics||{};byId[it.id]={views:+s.viewCount||0,likes:+s.likeCount||0,comments:+s.commentCount||0};});
  }
  POSTS.forEach(p=>{if(byId[p.id]){p.views=byId[p.id].views;p.likes=byId[p.id].likes;p.comments=byId[p.id].comments;}});
  render();
  setStatus('live · updated '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),true);
 }catch(e){setStatus('live update failed ('+e.message+') · showing last build',false);}
}

render();
refresh();
setInterval(refresh,120000);                         // refresh every 2 min while open
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();}); // and when you return to the tab
</script>
</body></html>"""
