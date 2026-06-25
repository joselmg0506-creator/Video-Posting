"""
Self-contained "Studio" analytics dashboard across ALL channels.

Aesthetic adopted from a shared Claude design (Manrope + Space Mono, warm charcoal palette,
All <-> per-channel tabs, suggestion cards), re-implemented in plain vanilla HTML/CSS/JS and
wired to OUR real, live data plus the features the mockup lacked:
  - Schedule Pulse: did each channel hit its 3 daily cron slots? (ops health for an unattended poster)
  - velocity (views/day), heat-score letter grades, engagement %, real YouTube thumbnails
  - best-posting-time heatmap, +Δ since last visit
  - auto-generated "Ways to grow / improve" advice computed from the real numbers

It renders client-side: on every load (and tab focus / every 2 min / tap the live dot) it calls
the YouTube Data API for current statistics + snippet + channel info, recomputes, and re-renders,
so a refresh shows live numbers. Live fetch needs `YT_API_KEY` (a browser key restricted to the
Pages domain), injected at build time; without it the page shows the build-time numbers + a banner.

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

# distinct accent per channel (assigned alphabetically) — warm "studio" trio from the design
_PALETTE = ["#FF6B5E", "#3DDC97", "#7C9CFF", "#D9A441", "#FF9A6B", "#6BB6FF", "#E3B341"]


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
        "posted_at": p.get("posted_at") or "",
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
            os.startfile(str(out))
        except Exception:
            pass
    return out


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0E0F13">
<title>VideoPOsting — Studio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0E0F13;--card:#16181E;--card2:#191B22;--bd:#23262F;--bd2:#262932;
 --tx:#F4F5F7;--mut:#8A8F9C;--mut2:#6B7180;--up:#3DDC97;--down:#FF6B5E;--amber:#D9A441}
*{box-sizing:border-box}
body{background:radial-gradient(120% 90% at 50% 0%,#1a1c22 0%,#121317 55%,#0c0d10 100%);
 background-attachment:fixed;color:var(--tx);margin:0;padding:0 0 48px;
 font-family:'Manrope',system-ui,-apple-system,Segoe UI,sans-serif;-webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
.wrap{max-width:560px;margin:0 auto;padding:0 18px}
a{color:inherit;text-decoration:none}
.mono{font-family:'Space Mono',ui-monospace,monospace}
.eyebrow{font-family:'Space Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut2);margin:14px 4px 8px}
.up{color:var(--up)} .down{color:var(--down)} .amber{color:var(--amber)}
.tnum{font-variant-numeric:tabular-nums}

/* header */
header{position:sticky;top:0;z-index:20;background:rgba(14,15,19,.82);backdrop-filter:blur(10px);
 display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:18px 0 14px;margin-bottom:2px}
.hl .tag{display:flex;align-items:center;gap:7px;font-family:'Space Mono',monospace;font-size:11px;letter-spacing:.12em;color:var(--mut2);text-transform:uppercase}
.dot{width:7px;height:7px;border-radius:50%;background:var(--down);animation:pl 1.8s ease-in-out infinite;cursor:pointer}
@keyframes pl{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.8)}}
.hl h1{font-size:26px;font-weight:800;letter-spacing:-.02em;line-height:1;margin:7px 0 0}
.rangepill{display:flex;align-items:center;gap:6px;background:#1A1C22;border:1px solid var(--bd2);border-radius:999px;
 padding:9px 13px;font-size:12.5px;font-weight:700;color:#C2C7D2;cursor:pointer;white-space:nowrap;margin-top:2px;font-family:inherit}
.rangepill span{color:var(--mut2);font-size:9px}

/* tabs */
.tabs{display:flex;gap:8px;overflow-x:auto;padding:2px 0 16px;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:0 0 auto;display:flex;align-items:center;gap:8px;padding:9px 15px;border-radius:999px;cursor:pointer;
 font-size:13px;font-weight:700;white-space:nowrap;background:transparent;border:1px solid var(--bd2);color:var(--mut);transition:all .15s;font-family:inherit}
.tab .tdot{width:8px;height:8px;border-radius:50%}

/* cards / sections */
.col{display:flex;flex-direction:column;gap:13px}
.hero{background:linear-gradient(165deg,#191B22,#141519);border:1px solid var(--bd2);border-radius:22px;padding:20px;overflow:hidden}
.hero .big{font-size:42px;font-weight:800;letter-spacing:-.03em;line-height:.9}
.hero .row{display:flex;align-items:flex-end;gap:11px;margin-top:8px}
.delt{display:flex;align-items:center;gap:4px;font-family:'Space Mono',monospace;font-size:13px;font-weight:700;padding-bottom:5px}
.spark{width:100%;height:64px;margin-top:14px;display:block}

.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:11px}
.stat{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:13px 13px}
.stat .l{font-family:'Space Mono',monospace;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut2);line-height:1.3}
.stat .v{font-size:19px;font-weight:800;letter-spacing:-.02em;margin-top:7px}
.stat .d{font-family:'Space Mono',monospace;font-size:11px;font-weight:700;margin-top:3px}
.stat.big2 .v{font-size:23px;margin-top:9px}

/* schedule pulse */
.pulse{background:var(--card);border:1px solid var(--bd);border-radius:18px;padding:15px 16px}
.pulse .top{display:flex;align-items:baseline;gap:8px;margin-bottom:11px}
.pulse .top b{font-size:14px;font-weight:700} .pulse .top .v{margin-left:auto;font-size:12px;color:var(--mut)}
.prow{display:grid;grid-template-columns:74px repeat(3,1fr);align-items:center;gap:6px;padding:4px 0}
.prow .nm{font-size:12.5px;font-weight:700}
.slot{height:26px;border-radius:8px;display:flex;align-items:center;justify-content:center;
 font-family:'Space Mono',monospace;font-size:10px;font-weight:700;border:1.5px solid var(--bd2);color:var(--mut)}
.slot.ontime{color:#0E0F13} .slot.missed{border-color:var(--down);color:var(--down)} .slot.pending{border-style:dashed}

/* channel cards */
.chcard{position:relative;display:flex;align-items:center;gap:13px;background:var(--card);border:1px solid var(--bd);
 border-radius:18px;padding:15px 16px 15px 18px;cursor:pointer;overflow:hidden}
.chcard .accent{position:absolute;left:0;top:0;bottom:0;width:4px}
.badge{flex:0 0 auto;width:46px;height:46px;border-radius:14px;display:flex;align-items:center;justify-content:center;
 font-size:19px;font-weight:800;color:#0E0F13;overflow:hidden}
.badge img{width:100%;height:100%;object-fit:cover}
.chcard .meta{flex:1;min-width:0}
.chcard .nm{font-size:15px;font-weight:700;letter-spacing:-.01em}
.chcard .sub{display:flex;gap:12px;margin-top:5px;font-size:11.5px;color:var(--mut)}
.chcard .sub b{color:#D7DAE2;font-weight:700}
.chev{flex:0 0 auto;color:#4C515E;font-size:18px}

/* suggestions */
.sug{display:flex;gap:13px;background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:14px 15px}
.sug .bar{flex:0 0 auto;width:5px;border-radius:3px;align-self:stretch}
.sug .tag{font-family:'Space Mono',monospace;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut2)}
.sug .imp{font-family:'Space Mono',monospace;font-size:9.5px;font-weight:700}
.sug h4{font-size:14px;font-weight:700;letter-spacing:-.01em;margin:6px 0 0}
.sug p{font-size:12.5px;color:var(--mut);line-height:1.45;margin:4px 0 0}

/* video rows */
.vid{display:flex;align-items:center;gap:13px;background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:10px 14px 10px 10px}
.vthumb{position:relative;flex:0 0 auto;width:38px;height:54px;border-radius:9px;overflow:hidden;background:#23262F}
.vthumb img{width:100%;height:100%;object-fit:cover}
.vid .vmeta{flex:1;min-width:0}
.vid .vt{font-size:13px;font-weight:600;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.vid .vs{font-family:'Space Mono',monospace;font-size:11px;color:var(--mut2);margin-top:5px}
.vid .vs b{color:#C2C7D2}
.vgrade{flex:0 0 auto;font-family:'Space Mono',monospace;font-weight:700;font-size:13px}

/* heatmap */
.heat-grid{display:grid;grid-template-columns:30px repeat(3,1fr);gap:5px}
.heat-grid .hh{font-family:'Space Mono',monospace;font-size:9.5px;color:var(--mut2);text-align:center;align-self:center}
.cell{height:28px;border-radius:7px;border:1px solid var(--bd2);display:flex;align-items:center;justify-content:center;
 font-family:'Space Mono',monospace;font-size:9.5px;color:#CFD2DA}

.empty{color:var(--mut);font-size:13.5px;padding:22px 16px;text-align:center;background:var(--card);border:1px dashed var(--bd2);border-radius:16px}
#banner:not(:empty){background:#1A1C22;border:1px solid var(--bd2);color:var(--mut);font-size:12.5px;line-height:1.5;border-radius:12px;padding:11px 14px;margin:12px 0}
#banner b{color:var(--tx)}
.foot{margin-top:26px;font-family:'Space Mono',monospace;font-size:10px;color:var(--mut2);text-align:center;line-height:1.7}
@media(min-width:600px){.wrap{padding:0 22px}.hero .big{font-size:46px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="wrap">

<header>
 <div class="hl">
  <div class="tag"><span class="dot" id="dot" title="tap to refresh"></span><span id="eyebrow">STUDIO</span></div>
  <h1 id="title">All channels</h1>
 </div>
 <button class="rangepill" id="range">All time <span>▾</span></button>
</header>

<div class="tabs" id="tabs"></div>
<div id="banner"></div>
<div class="col" id="view"></div>

<div class="foot">built __GEN__ · live numbers in your browser · 3 channels × 3 slots/day on Texas time</div>
</div>
<script>
const POSTS = __POSTS__;
const CHANNELS = __CHANNELS__;
const API_KEY = __APIKEY__;
const SLOTS = __SLOTS__;
const META = {};                       // channel -> {subs, totalViews, avatar}
const SLOT_LABEL = {17:'12p',20:'3p',1:'8p'};
let TAB='all', WIN='all';
const $=id=>document.getElementById(id);

/* ---------- helpers (real-data metrics) ---------- */
function fmt(n){n=+n||0;const a=Math.abs(n);
 if(a>=1e6)return(n/1e6).toFixed(a>=1e7?0:1).replace(/\.0$/,'')+'M';
 if(a>=1e3)return(n/1e3).toFixed(a>=1e4?0:1).replace(/\.0$/,'')+'K';return''+Math.round(n);}
function pctTxt(x){return x==null?'—':(x*100).toFixed(x<0.1?1:0)+'%';}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
function color(c){return CHANNELS[c]||'#FF6B5E';}
function initial(c){return (c||'?').charAt(0).toUpperCase();}
function ts(p){return Date.parse(p.posted_at||'')||0;}
function ageDays(p){const t=ts(p);return t?Math.max(0,(Date.now()-t)/864e5):9999;}
function ageHuman(p){const d=ageDays(p);return d<1?Math.max(1,Math.round(d*24))+'h ago':d<7?Math.round(d)+'d ago':d<30?Math.round(d/7)+'w ago':Math.round(d/30)+'mo ago';}
function velocity(p){return(+p.views||0)/Math.max(0.5,ageDays(p));}
function likeRate(p){return(p.likes!=null&&p.views)?p.likes/p.views:null;}
function commentRate(p){return(p.comments!=null&&p.views)?p.comments/p.views:null;}
function engRate(p){const v=+p.views||0;if(!v||p.likes==null)return null;return(p.likes+(p.comments||0))/v;}
function engScore(p){const v=+p.views||0;if(!v)return 0;return((p.likes||0)+3*(p.comments||0))/v;}
function median(a){if(!a.length)return 0;const s=[...a].sort((x,y)=>x-y);const m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2;}
function p90(ch,fn){const v=POSTS.filter(p=>p.channel===ch).map(fn).sort((a,b)=>a-b);if(!v.length)return 1;return v[Math.floor(v.length*0.9)]||v[v.length-1]||1;}
function heat(p){const vN=Math.min(1,velocity(p)/(p90(p.channel,velocity)||1));
 const eN=Math.min(1,engScore(p)/(p90(p.channel,engScore)||1e-9));
 const rec=Math.max(0,Math.min(1,1-ageDays(p)/14));return Math.round(100*(0.5*vN+0.35*eN+0.15*rec));}
function grade(h){return h>=85?'S':h>=70?'A':h>=55?'B':h>=40?'C':'D';}
function gColor(g){return{S:'#E3B341',A:'#3DDC97',B:'#7C9CFF',C:'#D9A441',D:'#6B7180'}[g];}
function winDays(){return WIN==='24h'?1:WIN==='7d'?7:WIN==='30d'?30:1e9;}
function inWin(p){return WIN==='all'||ageDays(p)<=winDays();}
function chPosts(ch){return POSTS.filter(p=>p.channel===ch&&inWin(p));}
function channels(){return Object.keys(CHANNELS).length?Object.keys(CHANNELS):[...new Set(POSTS.map(p=>p.channel))];}
function nowTime(){return new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});}
function sum(a,f){return a.reduce((s,x)=>s+(f?f(x):x),0);}
function avg(a){return a.length?a.reduce((s,x)=>s+x,0)/a.length:0;}

/* sparkline -> {line, area} point strings (min/max normalized) */
function spark(data,w,h,pad){pad=pad||6;if(!data.length)data=[0,0];if(data.length<2)data=[data[0],data[0]];
 const mn=Math.min(...data),mx=Math.max(...data),r=(mx-mn)||1,n=data.length;
 const pts=data.map((v,i)=>[+((i/(n-1))*w).toFixed(1),+(pad+(1-(v-mn)/r)*(h-2*pad)).toFixed(1)]);
 const line=pts.map(p=>p[0]+','+p[1]).join(' ');return {line,area:line+' '+w+','+h+' 0,'+h};}
function dailySeries(set){const m={};set.filter(p=>ts(p)).forEach(p=>{const d=new Date(ts(p)).toISOString().slice(0,10);m[d]=(m[d]||0)+(+p.views||0);});
 const days=Object.keys(m).sort();let c=0;return days.map(d=>(c+=m[d]));}

/* ---------- localStorage delta ---------- */
function loadSnap(){try{return JSON.parse(localStorage.getItem('vp_snap')||'null');}catch(e){return null;}}
function saveSnap(){const m={};POSTS.forEach(p=>m[p.id]=+p.views||0);
 try{localStorage.setItem('vp_snap',JSON.stringify({t:Date.now(),byId:m}));}catch(e){}}
const SNAP=loadSnap();
function deltaSince(set){if(!SNAP||!SNAP.byId)return null;let d=0,any=false;set.forEach(p=>{if(SNAP.byId[p.id]!=null){d+=(+p.views||0)-SNAP.byId[p.id];any=true;}});return any?d:null;}
function deltaPill(set){const d=deltaSince(set);if(d==null||d===0)return '';const cls=d>0?'up':'down';return '<div class="delt '+cls+'">'+(d>0?'▲':'▼')+' '+fmt(Math.abs(d))+'</div>';}

/* ---------- schedule pulse ---------- */
function slotTime(h){const now=Date.now(),d=new Date();let st=Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate())+h*36e5;if(st>now)st-=864e5;return st;}
function pulseRows(){return channels().map(ch=>({ch,slots:SLOTS.map(h=>{const st=slotTime(h);
 const hit=POSTS.some(p=>p.channel===ch&&Math.abs(ts(p)-st)<=90*6e4);
 return hit?'ontime':((Date.now()-st)<=90*6e4?'pending':'missed');})}));}
function pulseHtml(){const rows=pulseRows();const done=sum(rows,r=>r.slots.filter(s=>s==='ontime').length);
 const due=sum(rows,r=>r.slots.filter(s=>s!=='pending').length);const tot=rows.length*SLOTS.length;
 const v=due?(done===due?'<span class="up">all on track</span>':'<span class="down">'+(due-done)+' missed</span>'):'';
 return '<div class="pulse"><div class="top"><b>Posting pulse</b><span class="v">'+done+' / '+tot+' slots'+(v?' · '+v:'')+'</span></div>'+
  rows.map(r=>'<div class="prow"><span class="nm" style="color:'+color(r.ch)+'">'+esc(r.ch)+'</span>'+
   r.slots.map((s,i)=>{const lbl=SLOT_LABEL[SLOTS[i]]||('S'+(i+1));const sty=s==='ontime'?'background:'+color(r.ch)+';border-color:'+color(r.ch):'';
    return '<span class="slot '+s+'" style="'+sty+'">'+(s==='ontime'?'✓':s==='missed'?'✕':lbl)+'</span>';}).join('')+'</div>').join('')+'</div>';}

/* ---------- auto suggestions (real data) ---------- */
function suggestions(scope){ /* scope = null (global) or a channel name */
 const out=[];const chs=scope?[scope]:channels();
 const rows=pulseRows();
 chs.forEach(ch=>{const r=rows.find(x=>x.ch===ch);if(r){const miss=r.slots.filter(s=>s==='missed').length;
  if(miss)out.push({tag:'SCHEDULE',impact:'High impact',imp:'up',accent:color(ch),title:(scope?'':ch+': ')+'Post on schedule',body:(scope?'This channel':ch)+' missed '+miss+' of its 3 slots in the latest cycle — the Shorts feed rewards consistency.',w:5});}});
 const set=scope?chPosts(scope):POSTS.filter(inWin);
 const ers=set.map(engRate).filter(x=>x!=null);const er=avg(ers);
 if(ers.length&&er<0.02)out.push({tag:'HOOK',impact:'High impact',imp:'up',accent:scope?color(scope):'#FF6B5E',title:'Win the first second',body:'Engagement is '+pctTxt(er)+' — open on motion or the payoff so viewers stop the swipe.',w:4});
 chs.forEach(ch=>{const ps=chPosts(ch).filter(p=>ageDays(p)<7);if(ps.length){const best=ps.sort((a,b)=>velocity(b)-velocity(a))[0];
  if(best&&velocity(best)>1.4*(avg(chPosts(ch).map(velocity))||1))out.push({tag:'MOMENTUM',impact:'High impact',imp:'up',accent:color(ch),title:(scope?'':ch+': ')+'Ride the momentum',body:'"'+(best.title||'').slice(0,42)+'" is climbing fast ('+fmt(velocity(best))+'/day) — post more like it while the feed is pushing you.',w:4});}});
 chs.forEach(ch=>{const recent=chPosts(ch).filter(p=>ageDays(p)<7).length;
  if(recent<6)out.push({tag:'VOLUME',impact:'Med impact',imp:'amber',accent:color(ch),title:(scope?'':ch+': ')+'Post more at-bats',body:(scope?'This channel':ch)+' shipped '+recent+' Short'+(recent===1?'':'s')+' in 7 days — more uploads means more chances to spike.',w:3});});
 const generic=[
  {tag:'LOOP',impact:'Med impact',imp:'amber',accent:'#7C9CFF',title:'Design for the replay',body:'End on a line that flows back into the hook so the Short loops seamlessly — free extra views.',w:1},
  {tag:'CAPTIONS',impact:'Med impact',imp:'amber',accent:'#3DDC97',title:'Caption every line',body:'Most Shorts play on mute — big on-screen text lands the message without sound.',w:1}];
 const seen={};const uniq=out.concat(generic).filter(s=>{const k=s.tag+s.title;if(seen[k])return false;seen[k]=1;return true;});
 uniq.sort((a,b)=>b.w-a.w);return uniq.slice(0,3);}
function sugHtml(scope){const list=suggestions(scope);return list.map(s=>{const ic=s.imp==='up'?'var(--up)':s.imp==='amber'?'var(--amber)':'var(--down)';
 return '<div class="sug"><span class="bar" style="background:'+s.accent+'"></span><div style="flex:1;min-width:0">'+
  '<div style="display:flex;align-items:center;gap:9px"><span class="tag">'+s.tag+'</span><span class="imp" style="color:'+ic+'">'+s.impact+'</span></div>'+
  '<h4>'+esc(s.title)+'</h4><p>'+esc(s.body)+'</p></div></div>';}).join('');}

/* ---------- heatmap ---------- */
function heatHtml(){const cells={};POSTS.filter(p=>ts(p)).forEach(p=>{const d=new Date(ts(p));const wd=d.getUTCDay();const h=d.getUTCHours();
  let si=SLOTS.indexOf(h);if(si<0){let bd=99;SLOTS.forEach((s,idx)=>{const diff=Math.min(Math.abs(s-h),24-Math.abs(s-h));if(diff<bd){bd=diff;si=idx;}});}
  const k=wd+'-'+si;(cells[k]=cells[k]||[]).push(+p.views||0);});
 const a={};let mx=1;Object.entries(cells).forEach(([k,v])=>{a[k]=avg(v);mx=Math.max(mx,a[k]);});
 const WD=['Su','Mo','Tu','We','Th','Fr','Sa'];
 let h='<span class="hh"></span>'+SLOTS.map(s=>'<span class="hh">'+(SLOT_LABEL[s]||s)+'</span>').join('');
 for(let wd=0;wd<7;wd++){h+='<span class="hh">'+WD[wd]+'</span>';
  for(let si=0;si<SLOTS.length;si++){const v=a[wd+'-'+si];
   h+='<span class="cell" style="background:'+(v?'rgba(255,107,94,'+(0.1+0.8*v/mx).toFixed(2)+')':'transparent')+'">'+(v?fmt(v):'')+'</span>';}}
 return '<div class="pulse"><div class="heat-grid">'+h+'</div></div>';}

/* ---------- views ---------- */
function renderTabs(){const list=[{id:'all',name:'All',c:'#C9CED9',dot:false}].concat(channels().map(c=>({id:c,name:c,c:color(c),dot:true})));
 $('tabs').innerHTML=list.map(t=>{const on=TAB===t.id;const bg=on?(t.id==='all'?'#2A2D36':t.c+'24'):'transparent';
  const bd=on?(t.id==='all'?'#3A3E48':t.c+'66'):'var(--bd2)';const col=on?(t.id==='all'?'#F4F5F7':t.c):'var(--mut)';
  return '<div class="tab" data-t="'+esc(t.id)+'" style="background:'+bg+';border-color:'+bd+';color:'+col+'">'+
   (t.dot?'<span class="tdot" style="background:'+t.c+'"></span>':'')+esc(t.name)+'</div>';}).join('');
 [...$('tabs').children].forEach(el=>el.onclick=()=>{TAB=el.dataset.t;render();});}

function renderAllView(){const set=POSTS.filter(inWin);
 const tv=sum(set,p=>+p.views||0);
 const subs=channels().reduce((a,c)=>a+((META[c]&&META[c].subs!=null)?META[c].subs:0),0);
 const ers=set.map(engRate).filter(x=>x!=null);
 const kpis=[['Shorts',''+set.length],['Subscribers',subs?fmt(subs):'—'],['Avg engage',pctTxt(ers.length?avg(ers):null)]];
 const sp=spark(dailySeries(set),300,64,6);
 let h='';
 h+=pulseHtml();
 h+='<div class="hero"><div class="eyebrow" style="margin:0">Total views · all channels'+(WIN!=='all'?' · '+WIN:'')+'</div>'+
  '<div class="row"><div class="big tnum">'+fmt(tv)+'</div>'+deltaPill(set)+'</div>'+
  '<svg class="spark" viewBox="0 0 300 64" preserveAspectRatio="none"><polygon points="'+sp.area+'" fill="#FF6B5E" fill-opacity=".1"/>'+
  '<polyline points="'+sp.line+'" fill="none" stroke="#FF8A7E" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/></svg></div>';
 h+='<div class="grid3">'+kpis.map(k=>'<div class="stat"><div class="l">'+k[0]+'</div><div class="v tnum">'+k[1]+'</div></div>').join('')+'</div>';
 h+='<div class="eyebrow">Channels</div>';
 h+=channels().map(c=>{const ps=chPosts(c);const cv=sum(ps,p=>+p.views||0);const m=META[c]||{};const sp2=spark(dailySeries(ps),72,34,4);
  return '<div class="chcard" data-go="'+esc(c)+'"><span class="accent" style="background:'+color(c)+'"></span>'+
   '<span class="badge" style="background:'+color(c)+'">'+(m.avatar?'<img src="'+esc(m.avatar)+'">':initial(c))+'</span>'+
   '<span class="meta"><span class="nm">'+esc(c)+'</span><span class="sub">'+
    '<span><b>'+(m.subs!=null?fmt(m.subs):ps.length)+'</b> '+(m.subs!=null?'subs':'posts')+'</span><span><b>'+fmt(cv)+'</b> views</span></span></span>'+
   '<svg viewBox="0 0 72 34" preserveAspectRatio="none" style="flex:0 0 auto;width:72px;height:34px"><polygon points="'+sp2.area+'" fill="'+color(c)+'" fill-opacity=".13"/>'+
   '<polyline points="'+sp2.line+'" fill="none" stroke="'+color(c)+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>'+
   '<span class="chev">›</span></div>';}).join('');
 h+='<div class="eyebrow">Ways to grow</div>'+sugHtml(null);
 h+='<div class="eyebrow">Best posting times · avg views</div>'+heatHtml();
 $('view').innerHTML=h;
 [...$('view').querySelectorAll('[data-go]')].forEach(el=>el.onclick=()=>{TAB=el.dataset.go;render();});}

function renderChannelView(ch){const ps=chPosts(ch);const m=META[ch]||{};
 const cv=sum(ps,p=>+p.views||0);const ers=ps.map(engRate).filter(x=>x!=null);
 const vel=avg(ps.map(velocity));const subs=(m.subs!=null)?m.subs:null;const reach=(subs&&subs>0)?cv/subs:null;
 const sp=spark(dailySeries(ps),300,64,6);
 const mets=[['Views',fmt(cv)],['Engagement',pctTxt(ers.length?avg(ers):null)],
  ['Velocity',fmt(vel)+'/day'],['Reach ×subs',reach!=null?(reach<10?reach.toFixed(1):Math.round(reach))+'×':'—']];
 let h='<div class="hero"><div style="display:flex;align-items:center;gap:13px">'+
  '<span class="badge" style="width:48px;height:48px;border-radius:15px;background:'+color(ch)+'">'+(m.avatar?'<img src="'+esc(m.avatar)+'">':initial(ch))+'</span>'+
  '<div style="flex:1;min-width:0"><div style="font-size:17px;font-weight:800;letter-spacing:-.01em">'+esc(ch)+'</div>'+
   '<div style="font-size:12px;color:var(--mut);margin-top:2px">'+(m.subs!=null?fmt(m.subs)+' subscribers':ps.length+' Shorts')+'</div></div></div>'+
  '<div class="eyebrow" style="margin:18px 0 0">Views'+(WIN!=='all'?' · '+WIN:' · all time')+'</div>'+
  '<div class="row"><div class="big tnum">'+fmt(cv)+'</div>'+deltaPill(ps)+'</div>'+
  '<svg class="spark" viewBox="0 0 300 64" preserveAspectRatio="none"><polygon points="'+sp.area+'" fill="'+color(ch)+'" fill-opacity=".12"/>'+
  '<polyline points="'+sp.line+'" fill="none" stroke="'+color(ch)+'" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/></svg></div>';
 h+='<div class="grid2">'+mets.map(k=>'<div class="stat big2"><div class="l">'+k[0]+'</div><div class="v tnum">'+k[1]+'</div></div>').join('')+'</div>';
 h+='<div class="eyebrow">Top Shorts'+(WIN!=='all'?' · '+WIN:'')+'</div>';
 const top=[...ps].sort((a,b)=>heat(b)-heat(a)).slice(0,6);
 h+=top.map(p=>{const g=grade(heat(p));return '<a class="vid" href="'+esc(p.url)+'" target="_blank" rel="noopener">'+
  '<span class="vthumb"><img loading="lazy" decoding="async" src="https://i.ytimg.com/vi/'+esc(p.id)+'/mqdefault.jpg" onerror="this.style.opacity=0"></span>'+
  '<span class="vmeta"><span class="vt">'+esc(p.title||'(untitled)')+'</span>'+
   '<span class="vs"><b>'+fmt(p.views)+'</b> views · '+esc(ageHuman(p))+' · '+fmt(velocity(p))+'/day</span></span>'+
  '<span class="vgrade" style="color:'+gColor(g)+'">'+g+'</span></a>';}).join('')||'<div class="empty">No Shorts in this window yet.</div>';
 h+='<div class="eyebrow">Ways to improve</div>'+sugHtml(ch);
 $('view').innerHTML=h;}

function render(){renderTabs();
 $('title').textContent=TAB==='all'?'All channels':TAB;
 $('eyebrow').textContent=API_KEY?'STUDIO · LIVE':'STUDIO';
 if(TAB==='all')renderAllView();else renderChannelView(TAB);}

function setStatus(live){$('dot').style.background=live?'var(--up)':'var(--down)';}
function renderRange(){$('range').innerHTML=(WIN==='all'?'All time':WIN==='24h'?'24 hours':WIN==='7d'?'7 days':'30 days')+' <span>▾</span>';}
$('range').onclick=()=>{WIN=({all:'7d','7d':'30d','30d':'24h','24h':'all'})[WIN];renderRange();render();};
$('dot').onclick=()=>refresh();

/* ---------- live fetch ---------- */
async function refresh(){
 if(!API_KEY){$('banner').innerHTML='⚡ Live updates are off. Add a YouTube Data API key as GitHub secret <b>YT_API_KEY</b> (restricted to this domain) for real-time numbers. Showing the last build.';
  setStatus(false);render();return;}
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
  setStatus(true);render();saveSnap();
 }catch(e){setStatus(false);render();$('banner').innerHTML='⚠️ Live fetch failed ('+esc(e.message)+'). Showing the last build — if this says HTTP 403, the API key’s domain restriction may need updating.';}}
async function fetchChannels(){const map={};POSTS.forEach(p=>{if(p.channelId)map[p.channel]=p.channelId;});
 const ids=[...new Set(Object.values(map))];if(!ids.length)return;
 try{const r=await fetch('https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id='+ids.join(',')+'&key='+API_KEY);
  if(!r.ok)return;const j=await r.json();const byId={};
  (j.items||[]).forEach(it=>{const st=it.statistics||{},sn=it.snippet||{};byId[it.id]={
   subs:st.hiddenSubscriberCount?null:(('subscriberCount'in st)?+st.subscriberCount:null),
   totalViews:+st.viewCount||0,avatar:(sn.thumbnails&&sn.thumbnails.default)?sn.thumbnails.default.url:null};});
  Object.entries(map).forEach(([ch,cid])=>{if(byId[cid])META[ch]=byId[cid];});}catch(e){}}

renderRange();render();refresh();
setInterval(refresh,120000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
</script>
</body></html>"""
