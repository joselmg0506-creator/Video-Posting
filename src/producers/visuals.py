"""
Shared visual builders used by more than one producer:

- gen_images       : Flux text-to-image (fal.ai or Replicate)
- gen_image_urls   : Flux text-to-image returning fal-hosted URLs (to feed image-to-video)
- animate          : image-to-video via fal's async queue API (still -> moving clip)
- concat_clips     : stitch animated clips into one 1080x1920 silent video
- make_slideshow   : Ken-Burns slideshow from stills (+ optional music bed)
- make_gameplay_bg : looped gameplay b-roll background

Kept here so the story/character/brainrot-movie producers share one implementation.
Prompts passed to gen_images should already include any style suffix — this module is
style-agnostic.
"""
import random
import subprocess
import time
from pathlib import Path

import requests

from ..config import env
from ..transform.compose import _probe_duration


def _run(cmd: list[str], cwd: str | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "ignore")[-2000:]
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


# ───────────────────────────────── image generation ───────────────────────────────────

def _download(url: str, dest: Path) -> Path:
    img = requests.get(url, timeout=120)
    img.raise_for_status()
    dest.write_bytes(img.content)
    return dest


def _seed_at(seeds: "list[int | None] | None", i: int) -> "int | None":
    """The seed for prompt i, or None. Pinning a stable seed per recurring subject makes Flux
    render it more consistently across images (best-effort identity, not a LoRA)."""
    if seeds and i < len(seeds) and seeds[i] is not None:
        return int(seeds[i])
    return None


def gen_images(provider: str, model: str, prompts: list[str], out_dir: Path,
               image_size: str = "portrait_16_9",
               seeds: "list[int | None] | None" = None) -> list[Path]:
    if provider == "fal":
        return _gen_fal(model, prompts, out_dir, image_size, seeds)
    if provider == "replicate":
        return _gen_replicate(model, prompts, out_dir, seeds)
    raise ValueError(f"Unknown image_provider: {provider!r} (use 'fal' or 'replicate')")


def _gen_fal(model: str, prompts: list[str], out_dir: Path, image_size: str,
             seeds: "list[int | None] | None" = None) -> list[Path]:
    key = env("FAL_KEY", required=True)
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    paths: list[Path] = []
    for i, prompt in enumerate(prompts):
        payload = {"prompt": prompt, "image_size": image_size, "num_images": 1}
        seed = _seed_at(seeds, i)
        if seed is not None:
            payload["seed"] = seed
        r = requests.post(f"https://fal.run/{model}", headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        url = r.json()["images"][0]["url"]
        paths.append(_download(url, out_dir / f"img_{i}.jpg"))
    return paths


def _gen_replicate(model: str, prompts: list[str], out_dir: Path,
                   seeds: "list[int | None] | None" = None) -> list[Path]:
    import replicate
    paths: list[Path] = []
    for i, prompt in enumerate(prompts):
        inp = {"prompt": prompt, "aspect_ratio": "9:16", "num_outputs": 1}
        seed = _seed_at(seeds, i)
        if seed is not None:
            inp["seed"] = seed
        out = replicate.run(model, input=inp)
        url = str(out[0] if isinstance(out, (list, tuple)) else out)
        paths.append(_download(url, out_dir / f"img_{i}.jpg"))
    return paths


# ───────────────────────── image-to-video (fal queue API) ─────────────────────────────

def _fal_headers() -> dict:
    return {"Authorization": f"Key {env('FAL_KEY', required=True)}", "Content-Type": "application/json"}


def gen_image_urls(model: str, prompts: list[str],
                   image_size: str = "portrait_16_9",
                   seeds: "list[int | None] | None" = None) -> list[str]:
    """Generate Flux stills and return their fal-hosted URLs (NOT downloaded) so they can be
    fed straight into the image-to-video model. fal.ai only."""
    headers = _fal_headers()
    urls: list[str] = []
    for i, prompt in enumerate(prompts):
        payload = {"prompt": prompt, "image_size": image_size, "num_images": 1}
        seed = _seed_at(seeds, i)
        if seed is not None:
            payload["seed"] = seed
        r = requests.post(f"https://fal.run/{model}", headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        urls.append(r.json()["images"][0]["url"])
    return urls


def animate(image_url: str, motion_prompt: str, out: Path,
            model: str = "fal-ai/ltx-video-13b-distilled/image-to-video",
            num_frames: int = 97, max_wait: int = 480) -> Path:
    """Animate a still into a short moving clip via fal's ASYNC queue API (the sync endpoint
    times out on video). Submit -> poll status -> download the result. Returns the clip Path."""
    headers = _fal_headers()
    sub = requests.post(f"https://queue.fal.run/{model}", headers=headers, timeout=60,
                        json={"image_url": image_url, "prompt": motion_prompt,
                              "num_frames": num_frames})
    sub.raise_for_status()
    j = sub.json()
    status_url, response_url = j["status_url"], j["response_url"]
    waited = 0
    while waited < max_wait:
        time.sleep(5)
        waited += 5
        status = requests.get(status_url, headers=headers, timeout=30).json().get("status")
        if status == "COMPLETED":
            res = requests.get(response_url, headers=headers, timeout=60).json()
            vid = res.get("video") if isinstance(res, dict) else None
            url = vid.get("url") if isinstance(vid, dict) else None
            if not url:
                raise RuntimeError(f"fal image-to-video completed but returned no video "
                                   f"({model}): {str(res)[:200]}")
            out = Path(out)
            out.write_bytes(requests.get(url, timeout=300).content)
            return out
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal image-to-video failed ({model}): {status}")
    raise RuntimeError(f"fal image-to-video timed out after {max_wait}s ({model})")


def still_clip(image: Path, seconds: float, out: Path) -> Path:
    """A single still -> a 1080x1920 Ken-Burns clip of exactly `seconds` (slow zoom). Used by
    the stills (non-animated) story mode so each picture is shown for the length of its line."""
    frames = max(2, int(round(seconds * 30)))
    _run([
        "ffmpeg", "-y", "-i", str(image),
        "-vf", ("scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
                f"zoompan=z='min(zoom+0.0008,1.2)':d={frames}:"
                "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,setsar=1"),
        "-t", f"{seconds:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(out),
    ])
    return out


def concat_clips(clips: list[Path], out: Path, tmp_dir: Path,
                 music_dir: str | None = None) -> Path:
    """Normalize each animated clip to 1080x1920 / 30fps and concat into ONE silent video
    (the producer mixes narration over it later). Optional Content-ID-safe music bed."""
    norm: list[Path] = []
    for i, c in enumerate(clips):
        n = tmp_dir / f"clip_{i}.mp4"
        _run(["ffmpeg", "-y", "-i", str(c), "-an",
              "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                     "crop=1080:1920,fps=30,setsar=1",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
              str(n)])
        norm.append(n)
    listing = tmp_dir / "clips.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in norm), encoding="utf-8")
    silent = tmp_dir / "film_silent.mp4"
    # cwd=tmp_dir so the concat list can use bare filenames (sidesteps Windows path escaping)
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "clips.txt",
          "-c", "copy", str(silent)], cwd=str(tmp_dir))

    music = pick_music(music_dir) if music_dir else None
    if not music:
        return silent
    _run(["ffmpeg", "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(music),
          "-map", "0:v", "-map", "1:a", "-shortest",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", str(out)])
    return out


# ───────────────────────────────── backgrounds ────────────────────────────────────────

def make_gameplay_bg(broll_dir: str, seconds: float, out: Path) -> Path:
    """Silent 1080x1920 gameplay background of `seconds`: pick a random b-roll, seek to a
    random offset, loop if needed, fill-crop to vertical."""
    files = [p for p in Path(broll_dir).glob("*.mp4") if "speed_song" not in p.name.lower()]
    if not files:
        raise RuntimeError(f"No gameplay b-roll (*.mp4) found in {broll_dir}. "
                           "Drop a few looping gameplay clips there.")
    src = random.choice(files)
    pad = seconds + 0.4
    dur = _probe_duration(src) or 0.0
    start = random.uniform(0, dur - pad - 1) if dur > pad + 1 else 0.0
    _run([
        "ffmpeg", "-y", "-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(src),
        "-t", f"{pad:.2f}", "-an",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
               "crop=1080:1920,fps=30,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(out),
    ])
    return out


# ───────────────────────────────── slideshow ──────────────────────────────────────────

def pick_music(music_dir: str) -> Path | None:
    d = Path(music_dir)
    if not d.exists():
        return None
    tracks = [p for p in d.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")]
    return random.choice(tracks) if tracks else None


def make_slideshow(images: list[Path], seconds: float, out: Path, tmp_dir: Path,
                   music_dir: str | None = None, durations: list[float] | None = None) -> Path:
    """Ken-Burns slideshow: each still gets a slice with a slow zoom, concatenated, then (if a
    track exists) a Content-ID-safe music bed mixed under it.

    `durations` (one entry per image) times each still to when its narration is spoken, so the
    picture matches the story. Without it, images split `seconds` evenly.

    NOTE: the per-image command feeds a SINGLE frame (no -loop) so zoompan emits exactly
    `d` output frames — using -loop here makes zoompan multiply frames per looped input
    and effectively hang."""
    n = max(1, len(images))
    if durations and len(durations) == n:
        segs = [max(0.4, d) for d in durations]
    else:
        segs = [seconds / n] * n
    seg_paths: list[Path] = []
    for i, img in enumerate(images):
        seg = segs[i]
        sp = tmp_dir / f"seg_{i}.mp4"
        frames = max(2, int(round(seg * 30)))
        _run([
            "ffmpeg", "-y", "-i", str(img),
            "-vf", ("scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
                    f"zoompan=z='min(zoom+0.0008,1.2)':d={frames}:"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,setsar=1"),
            "-t", f"{seg:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(sp),
        ])
        seg_paths.append(sp)

    listing = tmp_dir / "segs.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in seg_paths), encoding="utf-8")
    silent = tmp_dir / "slideshow_silent.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", str(silent)])

    music = pick_music(music_dir) if music_dir else None
    if not music:
        return silent
    _run([
        "ffmpeg", "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(music),
        "-map", "0:v", "-map", "1:a", "-shortest",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        str(out),
    ])
    return out
