"""
Self-contained, mobile-first "Pulse Cockpit" analytics dashboard across ALL channels.

How it stays fresh: the page renders client-side in the browser. On every load (and on tab
focus, every 2 min, and when you tap the live dot) it calls the YouTube Data API for current
statistics + snippet + channel info, recomputes every metric, and re-renders — so a refresh
shows live numbers, not whatever was baked in at build time.

Everything below the data is derived client-side: velocity (views/day), heat score + letter
grades, engagement rates, per-channel scoreboard, a schedule-health pulse (did each channel
hit its 3 daily cron slots?), a trend chart, a velocity leaderboard, and a best-time heatmap.
All charts are inline SVG — no chart library, no CDN — so it loads instantly on a phone.

The live fetch needs a YouTube Data API key in env var `YT_API_KEY` (a browser key restricted
to your Pages domain), injected at build time. Without it the page still works: it shows the
counts baked in at build (fetched server-side via each channel's OAuth token) + a setup banner.

  python main.py --dashboard          # build data/dashboard.html and open it
  python main.py --dashboard --no-open # just build it
"""
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import env

# UTC hours of the 3 daily posting slots (must mirror .github/workflows/post.yml cron).
_SLOTS_UTC = [17, 20, 1]

# distinct accent per channel (assigned alphabetically — keep in sync with the JS)
_PALETTE = ["#58a6ff", "#3fb950", "#bc8cff", "#f0883e", "#f778ba", "#39c5cf", "#e3b341"]


def _token_map(cfg: dict) -> dict:
    return {c["name"]: c.get("token_file") for c in cfg.get("channels", [])}


def _fetch_stats(token_file: str, video_ids: list[str]) -> dict:
    """videos.list(statistics) for one channel's videos, batched by 50 (build-time fallback)."""
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
                    "likes": int(s["likeCount"]) if "likeCount" in s else None,
                    "comments": int(s["commentCount"]) if "commentCount" in s else None,
                }
        except Exception as e:
            print(f"  [dashboard] stats fetch failed: {e}")
    return out


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
        return stats.get(p["video_id"], {"views": 0, "likes": None, "comments": None})

    rows = sorted(posts, key=lambda p: p.get("posted_at", ""), reverse=True)
    posts_json = [{
        "id": p["video_id"],
        "title": (p.get("title") or "")[:140],
        "channel": p.get("channel") or p.get("source") or "?",
        "creator": p.get("creator") or "",
        "url": p.get("url") or f"https://youtube.com/shorts/{p['video_id']}",
        "posted_at": p.get("posted_at") or "",          # FULL iso timestamp (velocity/slots/heatmap)
        "views": s(p)["views"], "likes": s(p)["likes"], "comments": s(p)["comments"],
    } for p in rows]

    channel_names = sorted({pj["channel"] for pj in posts_json})
    channels = {name: _PALETTE[i % len(_PALETTE)] for i, name in enumerate(channel_names)}

    api_key = env("YT_API_KEY", "") or ""
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    page = (_TEMPLATE
            .replace("__POSTS__", _safe(json.dumps(posts_json)))
            .replace("__CHANNELS__", _safe(json.dumps(channels)))
            .replace("__SLOTS__", json.dumps(_SLOTS_UTC))
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
<title>VideoPOsting — Cockpit</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--card2:#1b222c;--bd:#30363d;--mut:#8b949e;--tx:#e6edf3;
 --ok:#3fb950;--warn:#f0883e;--bad:#f85149;--gold:#e3b341}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--tx);margin:0;padding:0 14px 40px;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,Arial,sans-serif;
 -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
.wrap{max-width:940px;margin:0 auto}
a{color:inherit;text-decoration:none}
.mut{color:var(--mut)} .tnum{font-variant-numeric:tabular-nums}

/* sticky header */
header{position:sticky;top:0;z-index:20;background:rgba(13,17,23,.86);backdrop-filter:blur(8px);
 display:flex;align-items:center;gap:10px;padding:12px 2px 10px;margin-bottom:2px;border-bottom:1px solid var(--bd)}
header .wm{font-weight:750;letter-spacing:-.01em;font-size:17px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(63,185,80,.6);
 animation:p 2s infinite;cursor:pointer;flex:none}
@keyframes p{0%{box-shadow:0 0 0 0 rgba(63,185,80,.5)}70%{box-shadow:0 0 0 7px rgba(63,185,80,0)}100%{box-shadow:0 0 0 0 rgba(63,185,80,0)}}
header .st{font-size:12px;color:var(--mut)}
header .delta{margin-left:auto;font-size:12px;font-weight:650;background:#15351f;color:#56d364;
 border:1px solid #1f5130;border-radius:999px;padding:3px 9px;white-space:nowrap}
header .delta.flat{background:#1b222c;color:var(--mut);border-color:var(--bd)}

h2{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
 margin:26px 2px 11px;font-weight:650;display:flex;align-items:center;gap:8px}
h2 .tag{font-size:10px;font-weight:700;border-radius:6px;padding:2px 7px;background:#1b222c;border:1px solid var(--bd);color:var(--mut)}
.section{margin-top:6px}

/* schedule pulse */
.pulse{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:13px 15px;margin-top:14px}
.pulse .top{display:flex;align-items:baseline;gap:8px;margin-bottom:11px}
.pulse .top b{font-size:15px} .pulse .top .v{color:var(--mut);font-size:12.5px;margin-left:auto;text-align:right}
.prow{display:grid;grid-template-columns:78px repeat(3,1fr);align-items:center;gap:6px;padding:5px 0}
.prow .nm{font-size:12.5px;font-weight:650}
.slot{height:26px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;border:1.5px solid var(--bd)}
.slot.ontime{color:#0d1117} .slot.missed{border-color:var(--bad);color:var(--bad)}
.slot.pending{border-style:dashed;color:var(--mut)}

/* hero */
.hero{position:relative;background:var(--card);border:1px solid var(--bd);border-radius:18px;
 padding:20px 18px 16px;margin-top:14px;overflow:hidden}
.hero .bg{position:absolute;left:0;right:0;bottom:0;height:62%;width:100%;opacity:.16;pointer-events:none}
.hero .lab{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);font-weight:650}
.hero .odo{font-size:clamp(46px,15vw,82px);font-weight:800;letter-spacing:-.03em;line-height:.98;margin:2px 0 6px}
.hero .pills{display:flex;gap:8px;flex-wrap:wrap;position:relative}
.mpill{background:var(--card2);border:1px solid var(--bd);border-radius:999px;padding:5px 11px;font-size:12.5px}
.mpill b{font-weight:700} .up{color:var(--ok)} .down{color:var(--bad)}
.hero .verdict{margin-top:12px;font-size:13.5px;line-height:1.45;color:#d6dde6;cursor:pointer;position:relative}
.hero .verdict .k{font-weight:700}

/* window pills */
.win{display:flex;gap:7px;margin:16px 2px 0;flex-wrap:wrap}
.win button{background:var(--card);border:1px solid var(--bd);color:var(--mut);border-radius:999px;
 padding:6px 14px;font-size:12.5px;font-weight:650;cursor:pointer;font-family:inherit}
.win button.on{background:#1f6feb22;border-color:#1f6feb;color:#79c0ff}

/* KPI strip */
.kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:12px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:13px 14px}
.kpi .l{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);font-weight:600}
.kpi .n{font-size:23px;font-weight:750;margin-top:3px}
.kpi .d{font-size:11.5px;margin-top:2px}

/* horizontal rails */
.rail{display:flex;gap:11px;overflow-x:auto;padding:2px 2px 8px;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch}
.rail::-webkit-scrollbar{height:0}
.mcard{flex:0 0 168px;scroll-snap-align:start;background:var(--card);border:1px solid var(--bd);border-radius:14px;overflow:hidden}
.thumb{width:100%;aspect-ratio:16/9;background:linear-gradient(100deg,#1b222c,#222b36,#1b222c);background-size:200% 100%;animation:sh 1.4s infinite;display:block;object-fit:cover}
@keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
.mcard .b{padding:9px 11px}
.mcard .t{font-size:12.5px;font-weight:600;line-height:1.3;height:32px;overflow:hidden}
.mcard .m{font-size:11.5px;color:var(--mut);margin-top:6px;display:flex;align-items:center;gap:6px}
.heat{font-weight:750}

/* scoreboard */
.scores{display:grid;grid-template-columns:1fr;gap:11px}
.score{position:relative;background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:14px 15px;overflow:hidden}
.score.lead{border-color:#3a4350;box-shadow:0 0 0 1px #2a313c,0 8px 24px -12px #000}
.score .glow{position:absolute;inset:0;opacity:.10;pointer-events:none}
.score .h{display:flex;align-items:center;gap:10px;position:relative}
.score .av{width:34px;height:34px;border-radius:50%;background:#222b36;flex:none;object-fit:cover}
.score .nm{font-weight:750;font-size:15px} .crown{margin-left:4px}
.score .subs{margin-left:auto;text-align:right;font-size:11.5px;color:var(--mut)}
.score .subs b{color:var(--tx);font-size:14px;font-weight:700}
.bars{margin-top:11px;display:grid;gap:7px}
.bar{display:grid;grid-template-columns:64px 1fr 42px;align-items:center;gap:8px;font-size:11px;color:var(--mut)}
.bar .track{height:7px;background:#0d1117;border-radius:6px;overflow:hidden}
.bar .fill{height:100%;border-radius:6px;transition:width .4s}
.bar .vv{text-align:right;color:var(--tx);font-weight:650}
.gradeR{position:absolute;right:13px;bottom:12px}

/* trend */
.panel{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:14px 14px 10px;margin-top:12px}
.trend{width:100%;height:170px;display:block}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px}
.lg{font-size:12px;color:var(--mut);cursor:pointer;display:flex;align-items:center;gap:6px}
.lg .sw{width:11px;height:11px;border-radius:3px} .lg.off{opacity:.4;text-decoration:line-through}

/* leaderboard */
.tools{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin-top:10px}
.seg{display:flex;gap:0;background:var(--card);border:1px solid var(--bd);border-radius:10px;overflow:hidden}
.seg button{background:none;border:none;color:var(--mut);padding:7px 11px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit}
.seg button.on{background:#1f6feb22;color:#79c0ff}
.search{flex:1;min-width:130px;background:var(--card);border:1px solid var(--bd);border-radius:10px;color:var(--tx);padding:8px 11px;font-size:13px;font-family:inherit}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.chip{font-size:11px;font-weight:650;border:1px solid var(--bd);border-radius:999px;padding:4px 11px;cursor:pointer;color:var(--mut);background:var(--card)}
.chip.on{color:#0d1117}
.board{display:grid;gap:8px;margin-top:11px}
.row{display:grid;grid-template-columns:26px 64px 1fr auto;gap:11px;align-items:center;
 background:var(--card);border:1px solid var(--bd);border-radius:13px;padding:9px 11px}
.row .rk{font-weight:750;color:var(--mut);text-align:center;font-size:13px}
.row .th{width:64px;aspect-ratio:16/9;border-radius:7px;object-fit:cover;background:#1b222c}
.row .mid{min-width:0}
.row .ti{font-size:13.5px;font-weight:600;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .sub{display:flex;align-items:center;gap:7px;margin-top:5px;font-size:11px;color:var(--mut);flex-wrap:wrap}
.cdot{width:8px;height:8px;border-radius:50%;flex:none}
.perf{height:5px;border-radius:4px;background:#0d1117;margin-top:6px;overflow:hidden;max-width:240px}
.perf i{display:block;height:100%;border-radius:4px}
.row .rt{text-align:right} .row .rt .v{font-weight:750;font-size:14px} .row .rt .vl{font-size:10.5px;color:var(--mut)}
.flash{animation:fl .8s ease}
@keyframes fl{0%{background:#15351f}100%{}}

/* grade ring */
.gr{font-weight:800;font-size:11px}

/* heatmap */
.heat-grid{display:grid;grid-template-columns:34px repeat(3,1fr);gap:5px;margin-top:6px}
.heat-grid .hh{font-size:10px;color:var(--mut);text-align:center;align-self:center}
.cell{height:30px;border-radius:7px;border:1px solid var(--bd);display:flex;align-items:center;justify-content:center;font-size:10px;color:#cfd7df}

.empty{color:var(--mut);font-size:14px;padding:24px 16px;text-align:center;background:var(--card);border:1px dashed var(--bd);border-radius:14px}
#banner:not(:empty){background:#1f2530;border:1px solid var(--bd);color:var(--mut);font-size:12.5px;line-height:1.5;border-radius:10px;padding:10px 13px;margin:12px 0}
#banner b{color:var(--tx)}
.foot{margin-top:26px;font-size:11px;color:var(--mut);text-align:center;line-height:1.6}

@media(min-width:700px){
 body{padding:0 22px 50px}
 .kpis{grid-template-columns:repeat(4,1fr)}
 .scores{grid-template-columns:repeat(3,1fr)}
 .hero .odo{font-size:74px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="wrap">

<header>
 <span class="dot" id="dot" title="tap to refresh now"></span>
 <span class="wm">📊 VideoPOsting</span>
 <span class="st" id="st">…</span>
 <span class="delta flat" id="hdelta">—</span>
</header>

<div id="banner"></div>

<div class="section" id="pulse"></div>
<div class="hero" id="hero"></div>
<div class="win" id="win"></div>
<div class="kpis" id="kpis"></div>

<h2 id="moversH" style="display:none">🔥 Movers <span class="tag">velocity now</span></h2>
<div class="rail" id="movers"></div>

<h2>🏆 Channel scoreboard</h2>
<div class="scores" id="scores"></div>

<h2>📈 Momentum <span class="tag" id="trendTag">cumulative</span></h2>
<div class="panel"><div id="trend"></div><div class="legend" id="legend"></div></div>

<h2>🎬 Leaderboard <span class="tag">heat score</span></h2>
<div class="tools">
 <div class="seg" id="sort"></div>
 <input class="search" id="q" placeholder="search title or creator…">
</div>
<div class="chips" id="chips"></div>
<div class="board" id="board"></div>

<h2>🗓️ Best posting times <span class="tag">avg views</span></h2>
<div class="panel"><div class="heat-grid" id="heat"></div></div>

<div class="foot">built __GEN__ · numbers refresh live in your browser · 3 channels × 3 slots/day on Texas time</div>
</div>
<script>
const POSTS = __POSTS__;
const CHANNELS = __CHANNELS__;
const API_KEY = __APIKEY__;
const SLOTS = __SLOTS__;            // UTC hours of the 3 daily posting slots
const META = {};                   // channel -> {channelId, subs, totalViews, avatar}
const SLOT_LABEL = {17:'12pm',20:'3pm',1:'8pm'};

let WIN='all', CH=null, SORT='trending', Q='';
const $=s=>document.getElementById(s);

/* ---------- helpers ---------- */
function fmt(n){n=+n||0;const a=Math.abs(n);
 if(a>=1e6)return(n/1e6).toFixed(a>=1e7?0:1).replace(/\.0$/,'')+'M';
 if(a>=1e3)return(n/1e3).toFixed(a>=1e4?0:1).replace(/\.0$/,'')+'K';return''+Math.round(n);}
function pctTxt(x){if(x==null)return'—';return(x*100).toFixed(x<0.1?1:0)+'%';}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
function color(c){return CHANNELS[c]||'#58a6ff';}
function ts(p){return Date.parse(p.posted_at||'')||0;}
function ageDays(p){const t=ts(p);return t?Math.max(0,(Date.now()-t)/864e5):9999;}
function ageHours(p){const t=ts(p);return t?Math.max(0,(Date.now()-t)/36e5):99999;}
function velocity(p){return(+p.views||0)/Math.max(0.5,ageDays(p));}
function likeRate(p){return(p.likes!=null&&p.views)?p.likes/p.views:null;}
function commentRate(p){return(p.comments!=null&&p.views)?p.comments/p.views:null;}
function engRate(p){const v=+p.views||0;if(!v||p.likes==null)return null;return(p.likes+(p.comments||0))/v;}  /* likes hidden -> unknowable; comments disabled -> genuinely 0 */
function engScore(p){const v=+p.views||0;if(!v)return 0;return((p.likes||0)+3*(p.comments||0))/v;}
function median(a){if(!a.length)return 0;const s=[...a].sort((x,y)=>x-y);const m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2;}
function ageBucket(p){const d=ageDays(p);return d<2?0:d<7?1:2;}
function chMedian(ch,b){const v=POSTS.filter(p=>p.channel===ch&&ageBucket(p)===b).map(p=>+p.views||0);return median(v)||1;}
function bucketN(ch,b){return POSTS.filter(p=>p.channel===ch&&ageBucket(p)===b).length;}
function outlier(p){const b=ageBucket(p);if(bucketN(p.channel,b)<3)return null;return(+p.views||0)/chMedian(p.channel,b);}  /* null until a bucket has enough peers to be meaningful */
function p90(ch,fn){const v=POSTS.filter(p=>p.channel===ch).map(fn).sort((a,b)=>a-b);if(!v.length)return 1;return v[Math.floor(v.length*0.9)]||v[v.length-1]||1;}
function heat(p){const vN=Math.min(1,velocity(p)/(p90(p.channel,velocity)||1));
 const eN=Math.min(1,engScore(p)/(p90(p.channel,engScore)||1e-9));
 const rec=Math.max(0,Math.min(1,1-ageDays(p)/14));
 return Math.round(100*(0.5*vN+0.35*eN+0.15*rec));}
function grade(h){return h>=85?'S':h>=70?'A':h>=55?'B':h>=40?'C':'D';}
function gColor(g){return{S:'#e3b341',A:'#3fb950',B:'#58a6ff',C:'#f0883e',D:'#8b949e'}[g];}
function winDays(){return WIN==='24h'?1:WIN==='7d'?7:WIN==='30d'?30:1e9;}
function active(){const d=winDays();return POSTS.filter(p=>(WIN==='all'||ageDays(p)<=d)&&(!CH||p.channel===CH));}
function channels(){return Object.keys(CHANNELS).length?Object.keys(CHANNELS):[...new Set(POSTS.map(p=>p.channel))];}
function nowTime(){return new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});}

/* ---------- localStorage deltas ---------- */
function loadSnap(){try{return JSON.parse(localStorage.getItem('vp_snap')||'null');}catch(e){return null;}}
function saveSnap(){const m={};POSTS.forEach(p=>m[p.id]=+p.views||0);
 try{localStorage.setItem('vp_snap',JSON.stringify({t:Date.now(),total:POSTS.reduce((a,p)=>a+(+p.views||0),0),byId:m}));}catch(e){}}
const SNAP=loadSnap();
function changedSince(p){return SNAP&&SNAP.byId&&SNAP.byId[p.id]!=null&&(+p.views||0)>SNAP.byId[p.id];}

/* ---------- schedule pulse ---------- */
function slotTime(h){const now=Date.now(),d=new Date();
 let st=Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate())+h*36e5;
 if(st>now)st-=864e5;return st;}   /* most-recent occurrence of this slot (avoids UTC-midnight false 'pending') */
function pulseRows(){
 const now=Date.now();
 return channels().map(ch=>({ch,slots:SLOTS.map(h=>{
  const st=slotTime(h);
  const hit=POSTS.some(p=>p.channel===ch&&Math.abs(ts(p)-st)<=90*6e4);
  return hit?'ontime':((now-st)<=90*6e4?'pending':'missed');
 })}));}
function renderPulse(){
 const rows=pulseRows();const done=rows.reduce((a,r)=>a+r.slots.filter(s=>s==='ontime').length,0);
 const due=rows.reduce((a,r)=>a+r.slots.filter(s=>s!=='pending').length,0);
 const ok=done===due&&due>0;
 $('pulse').innerHTML='<div class="pulse"><div class="top"><b>Today’s posting</b>'+
  '<span class="v">'+done+' of '+(rows.length*SLOTS.length)+' slots'+
  (due?(' · '+(ok?'<span style="color:var(--ok)">all on track</span>':'<span style="color:var(--warn)">'+(due-done)+' missed</span>')):'')+'</span></div>'+
  rows.map(r=>'<div class="prow"><span class="nm" style="color:'+color(r.ch)+'">'+esc(r.ch)+'</span>'+
   r.slots.map((s,i)=>{const lbl=SLOT_LABEL[SLOTS[i]]||('S'+(i+1));
    const sty=s==='ontime'?'background:'+color(r.ch)+';border-color:'+color(r.ch):'';
    return '<span class="slot '+s+'" style="'+sty+'" title="'+lbl+'">'+(s==='ontime'?'✓':s==='missed'?'✕':lbl)+'</span>';}).join('')+
  '</div>').join('')+'</div>';}

/* ---------- hero ---------- */
let _odoTarget=0,_odoCur=0;
function odo(to){const el=$('odo');if(!el)return;const from=_odoCur;_odoTarget=to;const t0=performance.now(),dur=700;
 (function step(t){const k=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-k,3);_odoCur=Math.round(from+(to-from)*e);
  el.textContent=fmt(_odoCur);if(k<1)requestAnimationFrame(step);else _odoCur=to;})(t0);}
function verdicts(){
 const set=active();const out=[];
 const today=set.filter(p=>ageDays(p)<1);
 if(today.length){const byCh={};today.forEach(p=>byCh[p.channel]=(byCh[p.channel]||0)+(+p.views||0));
  const top=Object.entries(byCh).sort((a,b)=>b[1]-a[1])[0];
  if(top)out.push('<span class="k" style="color:'+color(top[0])+'">'+esc(top[0])+'</span> leads today with <span class="k">'+fmt(top[1])+'</span> views');}
 const mover=[...set].sort((a,b)=>velocity(b)-velocity(a))[0];
 if(mover)out.push('top mover: <span class="k">'+esc((mover.title||'').slice(0,40))+'</span> at <span class="k">'+fmt(velocity(mover))+'/day</span>');
 const best=[...set].filter(p=>engRate(p)!=null).sort((a,b)=>engRate(b)-engRate(a))[0];
 if(best)out.push('best engagement: <span class="k">'+pctTxt(engRate(best))+'</span> on <span class="k">'+esc((best.title||'').slice(0,34))+'</span>');
 return out.length?out:['posting on Texas time — data fills in as Shorts go up'];}
let _vi=0,_vlist=[];
function renderHero(){
 const set=active();const tv=set.reduce((a,p)=>a+(+p.views||0),0);
 const tl=set.reduce((a,p)=>a+(p.likes||0),0),tc=set.reduce((a,p)=>a+(p.comments||0),0);
 const er=tv?(tl+tc)/tv:null;
 _vlist=verdicts();_vi=0;
 $('hero').innerHTML=heroSpark(set)+
  '<div class="lab">total views'+(WIN!=='all'?' · '+WIN:'')+(CH?' · '+esc(CH):'')+'</div>'+
  '<div class="odo" id="odo">'+fmt(tv)+'</div>'+
  '<div class="pills"><span class="mpill"><b>'+fmt(tl)+'</b> likes</span>'+
   '<span class="mpill"><b>'+fmt(tc)+'</b> comments</span>'+
   '<span class="mpill"><b>'+pctTxt(er)+'</b> engagement</span>'+
   '<span class="mpill"><b>'+set.length+'</b> videos</span></div>'+
  '<div class="verdict" id="verdict">'+_vlist[0]+'</div>';
 _odoCur=Math.round(tv*0.6);odo(tv);
 $('verdict').onclick=()=>{_vi=(_vi+1)%_vlist.length;$('verdict').innerHTML=_vlist[_vi];};}
function heroSpark(set){
 const byDay=dailyTotals(set);if(byDay.length<2)return'';
 const W=600,H=120,mx=Math.max(1,...byDay.map(d=>d.v));
 const X=i=>byDay.length<2?0:i/(byDay.length-1)*W,Y=v=>H-(v/mx)*H;
 let d='M0,'+H;byDay.forEach((p,i)=>d+=' L'+X(i).toFixed(1)+','+Y(p.v).toFixed(1));d+=' L'+W+','+H+' Z';
 return'<svg class="bg" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none"><path d="'+d+'" fill="#58a6ff"/></svg>';}
function dailyTotals(set){
 const m={};set.filter(p=>ts(p)).forEach(p=>{const d=new Date(ts(p)).toISOString().slice(0,10);m[d]=(m[d]||0)+(+p.views||0);});
 const days=Object.keys(m).sort();let c=0;return days.map(d=>({d,v:(c+=m[d])}));}

/* ---------- window pills + KPIs ---------- */
function renderWin(){const opts=[['24h','24h'],['7d','7d'],['30d','30d'],['all','All']];
 $('win').innerHTML=opts.map(o=>'<button class="'+(WIN===o[0]?'on':'')+'" data-w="'+o[0]+'">'+o[1]+'</button>').join('');
 [...$('win').children].forEach(b=>b.onclick=()=>{WIN=b.dataset.w;renderAll();});}
function renderKPIs(){
 const set=active();
 const vel=set.length?set.reduce((a,p)=>a+velocity(p),0)/set.length:0;
 const erArr=set.map(engRate).filter(x=>x!=null);const er=erArr.length?erArr.reduce((a,b)=>a+b,0)/erArr.length:null;
 const rows=pulseRows();const done=rows.reduce((a,r)=>a+r.slots.filter(s=>s==='ontime').length,0);
 const mover=[...set].sort((a,b)=>velocity(b)-velocity(a))[0];
 const cards=[
  ['Avg velocity',fmt(vel)+'<span class="mut" style="font-size:13px">/day</span>','views per day, per video'],
  ['Engagement',pctTxt(er),'likes+comments ÷ views'],
  ['Today',done+'<span class="mut" style="font-size:14px"> /'+(rows.length*SLOTS.length)+'</span>','slots posted on schedule'],
  ['Top mover',mover?fmt(velocity(mover))+'<span class="mut" style="font-size:13px">/day</span>':'—',mover?esc((mover.title||'').slice(0,28)):'no data yet'],
 ];
 $('kpis').innerHTML=cards.map(c=>'<div class="kpi"><div class="l">'+c[0]+'</div><div class="n tnum">'+c[1]+'</div><div class="d mut">'+c[2]+'</div></div>').join('');}

/* ---------- movers ---------- */
function renderMovers(){
 const set=[...active()].filter(p=>ageDays(p)<14).sort((a,b)=>velocity(b)-velocity(a)).slice(0,8);
 $('moversH').style.display=set.length?'':'none';
 $('movers').innerHTML=set.map(p=>{const h=heat(p),g=grade(h);
  return '<a class="mcard" href="'+esc(p.url)+'" target="_blank" rel="noopener">'+
   '<img class="thumb" loading="lazy" decoding="async" src="https://i.ytimg.com/vi/'+esc(p.id)+'/mqdefault.jpg" onerror="this.style.animation=\'none\'">'+
   '<div class="b"><div class="t">'+esc(p.title||'')+'</div>'+
   '<div class="m"><span class="cdot" style="background:'+color(p.channel)+'"></span>'+
   '<b>'+fmt(velocity(p))+'</b>/day '+(ageHours(p)<48?'· <b>'+fmt(p.views/Math.max(1,ageHours(p)))+'</b>/hr':'')+
   '<span class="heat" style="margin-left:auto;color:'+gColor(g)+'">'+g+'</span></div></div></a>';}).join('')||
  '<div class="empty" style="flex:1">No recent videos in this window.</div>';}

/* ---------- scoreboard ---------- */
function renderScores(){
 const chs=channels().map(ch=>{
  const ps=POSTS.filter(p=>p.channel===ch);
  const v=ps.reduce((a,p)=>a+(+p.views||0),0);
  const vel=ps.length?ps.reduce((a,p)=>a+velocity(p),0)/ps.length:0;
  const erA=ps.map(engRate).filter(x=>x!=null);const er=erA.length?erA.reduce((a,b)=>a+b,0)/erA.length:0;
  const pts=ps.reduce((a,p)=>a+heat(p),0);
  return {ch,ps,v,vel,er,pts};});
 const mv=Math.max(1,...chs.map(c=>c.v)),mvel=Math.max(1e-9,...chs.map(c=>c.vel)),mer=Math.max(1e-9,...chs.map(c=>c.er));
 chs.sort((a,b)=>b.pts-a.pts);
 $('scores').innerHTML=chs.map((c,i)=>{
  const col=color(c.ch),m=META[c.ch]||{},g=grade(c.ps.length?Math.round(c.pts/c.ps.length):0);
  const bar=(lab,val,max)=>'<div class="bar"><span>'+lab+'</span><span class="track"><i class="fill" style="width:'+Math.round(100*val/max)+'%;background:'+col+'"></i></span><span class="vv">'+(lab==='engagement'?pctTxt(c.er):fmt(val))+'</span></div>';
  return '<div class="score'+(i===0?' lead':'')+'" data-ch="'+esc(c.ch)+'">'+
   '<div class="glow" style="background:radial-gradient(120% 80% at 80% 0,'+col+',transparent)"></div>'+
   '<div class="h">'+(m.avatar?'<img class="av" src="'+esc(m.avatar)+'">':'<span class="av"></span>')+
    '<span class="nm" style="color:'+col+'">'+esc(c.ch)+(i===0?'<span class="crown">👑</span>':'')+'</span>'+
    '<span class="subs">'+(m.subs!=null?'<b>'+fmt(m.subs)+'</b> subs':'<b>'+c.ps.length+'</b> videos')+'</span></div>'+
   '<div class="bars">'+bar('views',c.v,mv)+bar('velocity',c.vel,mvel)+bar('engagement',c.er,mer)+'</div>'+
   gradeRing(g,col)+'</div>';}).join('');
 [...$('scores').children].forEach(el=>el.onclick=()=>{const ch=el.dataset.ch;CH=(CH===ch?null:ch);renderAll();});}
function gradeRing(g,col){const c=gColor(g);return '<svg class="gradeR" width="38" height="38" viewBox="0 0 38 38">'+
 '<circle cx="19" cy="19" r="15" fill="none" stroke="#0d1117" stroke-width="4"/>'+
 '<circle cx="19" cy="19" r="15" fill="none" stroke="'+c+'" stroke-width="4" stroke-linecap="round" stroke-dasharray="'+(94* ({S:1,A:.8,B:.62,C:.46,D:.3}[g])).toFixed(0)+' 999" transform="rotate(-90 19 19)"/>'+
 '<text x="19" y="23" text-anchor="middle" class="gr" fill="'+c+'">'+g+'</text></svg>';}

/* ---------- trend ---------- */
let TREND_OFF={};
function renderTrend(){
 const set=active().filter(p=>ts(p));const chs=channels().filter(c=>!TREND_OFF[c]);
 const days=[...new Set(set.map(p=>new Date(ts(p)).toISOString().slice(0,10)))].sort();
 if(days.length<2){$('trend').innerHTML='<div class="empty">Not enough history yet — the trend fills in as videos post across more days.</div>';renderLegend();return;}
 const W=600,H=170,pad=6;
 const cum={};chs.forEach(c=>cum[c]=0);
 const stack=days.map(d=>{chs.forEach(c=>{cum[c]+=set.filter(p=>p.channel===c&&new Date(ts(p)).toISOString().slice(0,10)===d).reduce((a,p)=>a+(+p.views||0),0);});return {d,v:{...cum}};});
 const maxY=Math.max(1,...stack.map(s=>chs.reduce((a,c)=>a+s.v[c],0)));
 const X=i=>pad+(W-2*pad)*(days.length<2?0:i/(days.length-1)),Y=v=>H-pad-(H-2*pad)*(v/maxY);
 let paths='',base=days.map(()=>0);
 chs.forEach(c=>{const top=stack.map((s,i)=>base[i]+s.v[c]);
  let d='M'+X(0).toFixed(1)+','+Y(base[0]).toFixed(1);
  stack.forEach((s,i)=>d+=' L'+X(i).toFixed(1)+','+Y(top[i]).toFixed(1));
  for(let i=stack.length-1;i>=0;i--)d+=' L'+X(i).toFixed(1)+','+Y(base[i]).toFixed(1);d+=' Z';
  paths+='<path d="'+d+'" fill="'+color(c)+'" fill-opacity=".5" stroke="'+color(c)+'" stroke-width="1.2"/>';base=top;});
 $('trend').innerHTML='<svg class="trend" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+paths+'</svg>';
 renderLegend();}
function renderLegend(){$('legend').innerHTML=channels().map(c=>'<span class="lg '+(TREND_OFF[c]?'off':'')+'" data-c="'+esc(c)+'"><span class="sw" style="background:'+color(c)+'"></span>'+esc(c)+'</span>').join('');
 [...$('legend').children].forEach(el=>el.onclick=()=>{const c=el.dataset.c;TREND_OFF[c]=!TREND_OFF[c];renderTrend();});}

/* ---------- leaderboard ---------- */
function renderTools(){
 const sorts=[['trending','Trending'],['newest','Newest'],['top','Top'],['eng','Engagement'],['worst','Worst']];
 $('sort').innerHTML=sorts.map(s=>'<button class="'+(SORT===s[0]?'on':'')+'" data-s="'+s[0]+'">'+s[1]+'</button>').join('');
 [...$('sort').children].forEach(b=>b.onclick=()=>{SORT=b.dataset.s;renderBoard();[...$('sort').children].forEach(x=>x.classList.toggle('on',x.dataset.s===SORT));});
 $('chips').innerHTML='<span class="chip '+(!CH?'on':'')+'" style="'+(!CH?'background:#e6edf3':'')+'" data-c="">all</span>'+
  channels().map(c=>'<span class="chip '+(CH===c?'on':'')+'" data-c="'+esc(c)+'" style="'+(CH===c?'background:'+color(c):'border-color:'+color(c)+';color:'+color(c))+'">'+esc(c)+'</span>').join('');
 [...$('chips').children].forEach(el=>el.onclick=()=>{CH=el.dataset.c||null;renderAll();});
 $('q').oninput=()=>{Q=$('q').value.toLowerCase();renderBoard();};}
function sortFn(){return{trending:(a,b)=>heat(b)-heat(a),newest:(a,b)=>ts(b)-ts(a),top:(a,b)=>(+b.views||0)-(+a.views||0),
 eng:(a,b)=>(engRate(b)||0)-(engRate(a)||0),worst:(a,b)=>heat(a)-heat(b)}[SORT];}
function renderBoard(){
 let set=active();if(Q)set=set.filter(p=>((p.title||'')+' '+(p.creator||'')).toLowerCase().includes(Q));
 set=[...set].sort(sortFn());
 $('board').innerHTML=set.map((p,i)=>{
  const h=heat(p),g=grade(h),o=outlier(p),lr=likeRate(p),cr=commentRate(p),col=color(p.channel);
  const medal=i===0?'🥇':i===1?'🥈':i===2?'🥉':(i+1);
  return '<a class="row'+(changedSince(p)?' flash':'')+'" href="'+esc(p.url)+'" target="_blank" rel="noopener">'+
   '<span class="rk">'+medal+'</span>'+
   '<img class="th" loading="lazy" decoding="async" src="https://i.ytimg.com/vi/'+esc(p.id)+'/mqdefault.jpg">'+
   '<span class="mid"><span class="ti">'+esc(p.title||'(untitled)')+'</span>'+
    '<span class="sub"><span class="cdot" style="background:'+col+'"></span>'+esc(p.channel)+
     ' · <b style="color:#cfd7df">'+fmt(velocity(p))+'</b>/day'+
     ' · '+(ageDays(p)<1?Math.round(ageHours(p))+'h':Math.round(ageDays(p))+'d')+
     ' · ♥ '+pctTxt(lr)+' · 💬 '+pctTxt(cr)+
     (o!=null?' <span style="color:'+(o>=1?'var(--ok)':'var(--mut)')+'">'+o.toFixed(1)+'×</span>':'')+'</span>'+
    '<span class="perf"><i style="width:'+Math.max(4,h).toFixed(0)+'%;background:'+col+'"></i></span></span>'+
   '<span class="rt"><span class="v tnum">'+fmt(p.views)+'</span><div class="vl">views</div>'+
    '<div class="gr" style="color:'+gColor(g)+'">'+g+'</div></span></a>';}).join('')||
  '<div class="empty">No videos match.</div>';}

/* ---------- heatmap (best posting times) ---------- */
function renderHeat(){
 const cells={};POSTS.filter(p=>ts(p)).forEach(p=>{const d=new Date(ts(p));const wd=d.getUTCDay();
  const h=d.getUTCHours();let si=SLOTS.indexOf(h);if(si<0){let best=0,bd=99;SLOTS.forEach((s,idx)=>{const diff=Math.min(Math.abs(s-h),24-Math.abs(s-h));if(diff<bd){bd=diff;best=idx;}});si=best;}
  const k=wd+'-'+si;(cells[k]=cells[k]||[]).push(+p.views||0);});
 const avg={};let mx=1;Object.entries(cells).forEach(([k,a])=>{avg[k]=a.reduce((x,y)=>x+y,0)/a.length;mx=Math.max(mx,avg[k]);});
 const WD=['Su','Mo','Tu','We','Th','Fr','Sa'];
 let html='<span class="hh"></span>'+SLOTS.map(s=>'<span class="hh">'+(SLOT_LABEL[s]||s)+'</span>').join('');
 for(let wd=0;wd<7;wd++){html+='<span class="hh">'+WD[wd]+'</span>';
  for(let si=0;si<SLOTS.length;si++){const k=wd+'-'+si,v=avg[k];
   html+='<span class="cell" style="background:'+(v?'rgba(88,166,255,'+(0.12+0.78*v/mx).toFixed(2)+')':'transparent')+'" title="'+(v?fmt(v)+' avg views':'no posts')+'">'+(v?fmt(v):'')+'</span>';}}
 $('heat').innerHTML=html;}

/* ---------- orchestration ---------- */
function renderAll(){renderPulse();renderHero();renderWin();renderKPIs();renderMovers();renderScores();renderTrend();renderTools();renderBoard();renderHeat();updateDelta();}
function updateDelta(){const total=POSTS.reduce((a,p)=>a+(+p.views||0),0);
 if(SNAP&&SNAP.total!=null&&total>SNAP.total){const d=total-SNAP.total;const hrs=(Date.now()-SNAP.t)/36e5;
  $('hdelta').className='delta';$('hdelta').textContent='▲ '+fmt(d)+' views'+(hrs>1?' since last visit':'');}
 else{$('hdelta').className='delta flat';$('hdelta').textContent=fmt(total)+' total';}}
function setStatus(t,live){$('st').innerHTML=esc(t);$('dot').style.background=live?'var(--ok)':'#8b949e';}

async function refresh(){
 if(!API_KEY){$('banner').innerHTML='⚡ Live updates are off. Add a YouTube Data API key as GitHub secret <b>YT_API_KEY</b> (restricted to this domain) for real-time numbers. Showing the last build.';
  setStatus('last build',false);renderAll();return;}
 setStatus('updating…',false);
 try{
  const ids=[...new Set(POSTS.map(p=>p.id).filter(Boolean))];const byId={};
  for(let i=0;i<ids.length;i+=50){
   const r=await fetch('https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id='+ids.slice(i,i+50).join(',')+'&key='+API_KEY);
   if(!r.ok)throw new Error('HTTP '+r.status);const j=await r.json();
   (j.items||[]).forEach(it=>{const s=it.statistics||{},sn=it.snippet||{};byId[it.id]={
    views:+s.viewCount||0,likes:('likeCount'in s)?+s.likeCount:null,comments:('commentCount'in s)?+s.commentCount:null,
    publishedAt:sn.publishedAt,channelId:sn.channelId};});}
  POSTS.forEach(p=>{const u=byId[p.id];if(u){p.views=u.views;p.likes=u.likes;p.comments=u.comments;
   if(u.publishedAt)p.posted_at=u.publishedAt;if(u.channelId)p.channelId=u.channelId;}});
  await fetchChannels();
  renderAll();setStatus('live · '+nowTime(),true);saveSnap();
 }catch(e){setStatus('offline · '+e.message,false);renderAll();}}
async function fetchChannels(){
 const map={};POSTS.forEach(p=>{if(p.channelId)map[p.channel]=p.channelId;});
 const ids=[...new Set(Object.values(map))];if(!ids.length)return;
 try{const r=await fetch('https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id='+ids.join(',')+'&key='+API_KEY);
  if(!r.ok)return;const j=await r.json();const byId={};
  (j.items||[]).forEach(it=>{const st=it.statistics||{},sn=it.snippet||{};byId[it.id]={
   subs:st.hiddenSubscriberCount?null:(('subscriberCount'in st)?+st.subscriberCount:null),
   totalViews:+st.viewCount||0,avatar:(sn.thumbnails&&sn.thumbnails.default)?sn.thumbnails.default.url:null};});
  Object.entries(map).forEach(([ch,cid])=>{if(byId[cid])META[ch]=byId[cid];});}catch(e){}}

$('dot').onclick=()=>refresh();
renderAll();refresh();
setInterval(refresh,120000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
</script>
</body></html>"""
