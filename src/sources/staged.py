"""
Stage YouTube clips locally -> a GitHub Release the cloud can use.

YouTube blocks DOWNLOADS from datacenter IPs (GitHub Actions) but not from a home IP. So on the
LOCAL machine we grab the BEST moments from the priority YouTube creators, trim them to 9:16
Shorts, upload them to a 'yt-clips' Release (+ manifest), and the cloud pulls them from there —
exactly like the gameplay b-roll — with no live YouTube download in the cloud.

Getting the BEST parts (not just the start of a long stream), two ways combined:
  1. creators' OWN videos -> download only the windows around YouTube's "most replayed" peaks
     (the genuinely most-rewatched moments). Falls back to the opening window when a video has
     no heatmap yet.
  2. clip_searches -> yt-dlp search ("kai cenat clips") surfaces the viral, already-curated
     highlight clips; we stage the short ones. Free (no API quota), small + fast downloads.

  python main.py --stage-youtube     # run on the laptop whenever it's on; ONLY stages, never posts

Cloud read path (`available_clips`, `download_staged`) uses public Release URLs — no auth/gh.
Staging (`stage`) uses `gh` (authenticated locally) to manage the Release.
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import Clip

TAG = "yt-clips"
SOURCE = "youtube_staged"


def _repo_slug() -> str:
    s = os.environ.get("GITHUB_REPOSITORY")
    if s:
        return s
    try:
        url = subprocess.check_output(["git", "config", "--get", "remote.origin.url"],
                                      text=True).strip()
        m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    raise RuntimeError("Can't determine repo (set GITHUB_REPOSITORY or a github remote).")


def _asset(name: str, slug: str | None = None) -> str:
    slug = slug or _repo_slug()
    return f"https://github.com/{slug}/releases/download/{TAG}/{name}"


def _safe(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", cid) + ".mp4"


# ───────────────────────── cloud read path (no auth, public URLs) ─────────────────────────

def available_clips(cfg: dict) -> list[Clip]:
    """Staged clips the cloud can post, read from the public manifest. [] if none/disabled."""
    yc = cfg["sources"].get("youtube_staged", {})
    if not yc.get("enabled", True):
        return []
    try:
        slug = _repo_slug()
        r = requests.get(_asset("manifest.json", slug), timeout=20)
        if r.status_code != 200:
            return []
        man = r.json()
    except Exception as e:
        print(f"  [staged] manifest read failed: {e}")
        return []
    out: list[Clip] = []
    for c in man.get("clips", []):
        out.append(Clip(id=c["id"], title=c.get("title", ""), source=SOURCE,
                        creator=c.get("creator", ""),
                        download_url=_asset(_safe(c["id"]), slug),
                        duration=c.get("duration"), view_count=c.get("view_count")))
    return out


def download_staged(clip: Clip, dest_dir: Path) -> Path:
    """Download an already-processed (9:16, trimmed) staged clip from its Release URL."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / _safe(clip.id)
    with requests.get(clip.download_url, timeout=180, stream=True) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return out


# ───────────────────────── local staging helpers ─────────────────────────

def _gh(args: list[str], slug: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args, "-R", slug], capture_output=True, text=True, check=check)


def _ensure_release(slug: str) -> None:
    if _gh(["release", "view", TAG], slug, check=False).returncode != 0:
        _gh(["release", "create", TAG, "-t", "Staged YouTube clips",
             "-n", "Locally-downloaded, pre-trimmed YouTube clips the cloud posts from."], slug)


def _list_assets(slug: str) -> list[str]:
    r = _gh(["release", "view", TAG, "--json", "assets", "-q", ".assets[].name"], slug, check=False)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []


def _load_manifest(slug: str) -> dict:
    try:
        r = requests.get(_asset("manifest.json", slug), timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"clips": []}


def _extract_info(clip: Clip) -> dict:
    import yt_dlp
    from .youtube import _common_opts
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                           **_common_opts()}) as y:
        return y.extract_info(clip.download_url, download=False) or {}


def _pick_segments(info: dict, max_peaks: int, clip_len: int, cap: int):
    """Return ([(start,end), ...], used_heatmap). Windows around the top 'most replayed' peaks
    when the heatmap exists; otherwise the opening window (capped)."""
    dur = info.get("duration") or 0
    hm = info.get("heatmap") or []
    if hm and dur > clip_len * 1.5:
        chosen: list[float] = []
        for p in sorted(hm, key=lambda h: -(h.get("value") or 0)):
            s = p.get("start_time", 0)
            if all(abs(s - c) > clip_len * 1.2 for c in chosen):
                chosen.append(s)
            if len(chosen) >= max_peaks:
                break
        segs = [(max(0, s - 8), min(dur, s - 8 + clip_len + 10)) for s in sorted(chosen)]
        return segs, True
    return [(0, min(dur or cap, cap))], False


def _download_segment(clip: Clip, dest_dir: Path, start: float, end: float, tag: str) -> Path:
    """Download only the [start, end] window of a YouTube video (bounds size + time)."""
    import yt_dlp
    from .youtube import _common_opts
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = str(dest_dir / (re.sub(r"[^A-Za-z0-9_-]", "_", clip.id) + f"{tag}_raw.%(ext)s"))
    opts = {
        "outtmpl": out,
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4", "quiet": True, "no_warnings": True,
        "download_ranges": yt_dlp.utils.download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        **_common_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(clip.download_url, download=True)
        return Path(y.prepare_filename(info)).with_suffix(".mp4")


def _ytsearch(query: str, n: int) -> list[Clip]:
    """Surface viral clips via yt-dlp search (no API quota)."""
    import yt_dlp
    from .youtube import _common_opts, _id_for
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                           "extract_flat": True, **_common_opts()}) as y:
        info = y.extract_info(f"ytsearch{n}:{query}", download=False) or {}
    out: list[Clip] = []
    for e in (info.get("entries") or []):
        vid = e.get("url") or e.get("id")
        if not vid:
            continue
        watch = vid if str(vid).startswith("http") else f"https://www.youtube.com/watch?v={vid}"
        out.append(Clip(id=_id_for(watch), title=e.get("title", "clip"), source="youtube",
                        creator=e.get("channel") or e.get("uploader") or query,
                        download_url=watch, duration=e.get("duration"), view_count=e.get("view_count")))
    return out


def stage(state, cfg: dict) -> None:
    """Stage the BEST YouTube moments to the 'yt-clips' Release. ONLY stages — never posts."""
    from ..processor.video import process as process_video
    from .youtube import recent_uploads

    yc = cfg["sources"].get("youtube_staged", {})
    creators = yc.get("creators") or []
    clip_searches = yc.get("clip_searches") or []
    per_creator = int(yc.get("per_creator", 1))
    peaks = int(yc.get("peaks_per_video", 2))
    per_search = int(yc.get("per_search", 2))
    keep = int(yc.get("keep", 14))
    cap = int(yc.get("download_cap_seconds", 600))
    tab = cfg["sources"].get("youtube", {}).get("tab", "videos")
    pc = cfg["processing"]
    clip_len = int(pc["max_duration_seconds"])
    downloads = Path(cfg["paths"]["downloads"])
    processed = Path(cfg["paths"]["processed"])
    processed.mkdir(parents=True, exist_ok=True)

    slug = _repo_slug()
    _ensure_release(slug)
    man = _load_manifest(slug)
    man.setdefault("clips", [])
    have = {c["id"] for c in man["clips"]}
    added = 0

    def _stage_one(clip: Clip, start: float, end: float, seg_id: str, tag: str) -> bool:
        nonlocal added
        if seg_id in have or state.is_posted(seg_id) or state.is_pending(seg_id):
            return False
        raw = _download_segment(clip, downloads, start, end, tag)
        out = processed / (re.sub(r"[^A-Za-z0-9_-]", "_", seg_id) + "_staged.mp4")
        process_video(raw, out, width=pc["target_width"], height=pc["target_height"],
                      fit=pc["fit_mode"], max_duration=clip_len, peak_trim=pc.get("peak_trim", True))
        asset = out.with_name(_safe(seg_id))
        if asset != out:
            shutil.copy(out, asset)
        _gh(["release", "upload", TAG, str(asset), "--clobber"], slug)
        man["clips"].append({"id": seg_id, "title": clip.title, "creator": clip.creator,
                             "duration": clip.duration, "view_count": clip.view_count,
                             "staged_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        have.add(seg_id)
        added += 1
        print(f"    staged -> {asset.name}")
        return True

    # 1) creators' OWN videos at the most-replayed peaks (best moments)
    for handle in creators:
        try:
            ups = recent_uploads(handle, limit=per_creator + 5, tab=tab)
        except Exception as e:
            print(f"  [stage] {handle}: list failed: {e}")
            continue
        mined = 0
        for clip in ups:
            if mined >= per_creator:
                break
            try:
                info = _extract_info(clip)
                segs, used_hm = _pick_segments(info, peaks, clip_len, cap)
                print(f"  [stage] {handle}: {clip.title[:48]!r} "
                      f"({'most-replayed' if used_hm else 'opening'}, {len(segs)} seg)")
                got = False
                for s, e in segs:
                    seg_id = clip.id + (f":{int(s)}" if used_hm else "")
                    try:
                        got = _stage_one(clip, s, e, seg_id, f"_{int(s)}") or got
                    except Exception as ex:
                        print(f"    segment @{int(s)}s failed: {ex}")
                if got:
                    mined += 1
            except Exception as e:
                print(f"  [stage] {clip.title[:40]!r} failed: {e}")

    # 2) viral curated clips via search. "<creator> clips" mostly surfaces COMPILATIONS, so we
    #    prefer genuine short clips, and for longer ones download just the first ~150s and
    #    peak-trim to the best 35s (a compilation is wall-to-wall highlights anyway).
    for q in clip_searches:
        try:
            results = _ytsearch(q, per_search + 8)
        except Exception as e:
            print(f"  [stage] search {q!r} failed: {e}")
            continue
        results.sort(key=lambda c: c.duration or 9999)   # genuine short clips before compilations
        n = 0
        for clip in results:
            if n >= per_search:
                break
            d = clip.duration or 0
            kind = "clip" if d and d <= 180 else "compilation→peak"
            print(f"  [stage] search {q!r}: {clip.title[:46]!r} ({kind})")
            try:
                if _stage_one(clip, 0, min(d or 150, 150), clip.id, ""):
                    n += 1
            except Exception as ex:
                print(f"    {clip.title[:40]!r} failed: {ex}")

    # keep only the newest `keep`; delete Release assets no longer in the manifest
    man["clips"] = man["clips"][-keep:]
    man["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    kept = {_safe(c["id"]) for c in man["clips"]} | {"manifest.json"}
    for name in _list_assets(slug):
        if name not in kept:
            _gh(["release", "delete-asset", TAG, name, "-y"], slug, check=False)

    mpath = processed / "manifest.json"
    mpath.write_text(json.dumps(man, indent=2), encoding="utf-8")
    _gh(["release", "upload", TAG, str(mpath), "--clobber"], slug)
    print(f"  staged {added} new clip(s); {len(man['clips'])} in the cloud cache (tag '{TAG}').")
