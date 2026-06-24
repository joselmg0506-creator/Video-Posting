"""
Shared visual builders used by more than one producer:

- gen_images       : Flux text-to-image (fal.ai or Replicate)
- make_slideshow   : Ken-Burns slideshow from stills (+ optional music bed)
- make_gameplay_bg : looped gameplay b-roll background

Kept here so both the story channel (ai_illustrated visual) and the character channel
share one implementation. Prompts passed to gen_images should already include any style
suffix — this module is style-agnostic.
"""
import random
import subprocess
from pathlib import Path

import requests

from ..config import env
from ..transform.compose import _probe_duration


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "ignore")[-2000:]
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


# ───────────────────────────────── image generation ───────────────────────────────────

def _download(url: str, dest: Path) -> Path:
    img = requests.get(url, timeout=120)
    img.raise_for_status()
    dest.write_bytes(img.content)
    return dest


def gen_images(provider: str, model: str, prompts: list[str], out_dir: Path,
               image_size: str = "portrait_16_9") -> list[Path]:
    if provider == "fal":
        return _gen_fal(model, prompts, out_dir, image_size)
    if provider == "replicate":
        return _gen_replicate(model, prompts, out_dir)
    raise ValueError(f"Unknown image_provider: {provider!r} (use 'fal' or 'replicate')")


def _gen_fal(model: str, prompts: list[str], out_dir: Path, image_size: str) -> list[Path]:
    key = env("FAL_KEY", required=True)
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    paths: list[Path] = []
    for i, prompt in enumerate(prompts):
        r = requests.post(
            f"https://fal.run/{model}",
            headers=headers,
            json={"prompt": prompt, "image_size": image_size, "num_images": 1},
            timeout=180,
        )
        r.raise_for_status()
        url = r.json()["images"][0]["url"]
        paths.append(_download(url, out_dir / f"img_{i}.jpg"))
    return paths


def _gen_replicate(model: str, prompts: list[str], out_dir: Path) -> list[Path]:
    import replicate
    paths: list[Path] = []
    for i, prompt in enumerate(prompts):
        out = replicate.run(model, input={"prompt": prompt, "aspect_ratio": "9:16",
                                          "num_outputs": 1})
        url = str(out[0] if isinstance(out, (list, tuple)) else out)
        paths.append(_download(url, out_dir / f"img_{i}.jpg"))
    return paths


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
                   music_dir: str | None = None) -> Path:
    """Ken-Burns slideshow: each still gets an equal slice with a slow zoom, concatenated,
    then (if a track exists) a Content-ID-safe music bed mixed under it.

    NOTE: the per-image command feeds a SINGLE frame (no -loop) so zoompan emits exactly
    `d` output frames — using -loop here makes zoompan multiply frames per looped input
    and effectively hang."""
    n = max(1, len(images))
    seg = seconds / n
    seg_paths: list[Path] = []
    for i, img in enumerate(images):
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
