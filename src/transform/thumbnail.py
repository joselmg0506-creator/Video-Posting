"""
Build a custom cover/thumbnail for a Short and (the caller) upload it via the YouTube API.

Grabs a strong frame from the FINISHED video and overlays a short, bold, ALL-CAPS title with a
heavy black outline (legible on any background — the same look as our captions). The frame is
taken at the video MIDPOINT so the first-seconds hook banner is gone, and the title sits in the
UPPER third, clear of the lower-third karaoke captions, so the cover never double-stacks text.

Pure Pillow + ffmpeg frame-grab — no image model, no GPU. Works for every channel since it reads
a frame from the rendered video (a real clip frame, or the AI still for stories/characters).

Best-effort: any failure returns None and the caller just keeps YouTube's auto-picked frame.
"""
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .compose import _probe_duration

# Bold fonts by platform; falls back to Pillow's scalable bundled font (>=10.1) if none resolve.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _font(size: int):
    for p in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)     # Pillow >=10.1: scalable bundled font
    except TypeError:
        return ImageFont.load_default()


def _clean(title: str) -> str:
    """Hashtags removed, smart punctuation normalised, emoji/non-Latin glyphs dropped (the font
    can't render them), collapsed whitespace, UPPERCASED."""
    t = (title or "")
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("—", "-")):
        t = t.replace(a, b)
    t = re.sub(r"#\w+", "", t)
    t = "".join(ch for ch in t if ch.isascii())
    return re.sub(r"\s+", " ", t).strip().upper()


def _grab_frame(video: Path, out: Path, at: float) -> Path | None:
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
        capture_output=True,
    )
    return out if (r.returncode == 0 and out.exists()) else None


def _wrap(draw, text: str, font, max_w: float, max_lines: int = 3) -> list[str]:
    lines: list[str] = []
    cur = ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if not cur or draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                return lines[:max_lines]
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines]


def make_thumbnail(video: Path, title: str, out: Path) -> Path | None:
    """Frame from `video` + bold ALL-CAPS title overlay -> JPEG at `out`. None on any failure."""
    try:
        video = Path(video)
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        dur = _probe_duration(video) or 2.0
        at = max(0.5, dur * 0.5)                       # midpoint: past the hook banner
        frame = _grab_frame(video, out.with_name(out.stem + "_frame.jpg"), at)
        if not frame:
            return None

        img = Image.open(frame).convert("RGB")
        W, H = img.size
        text = _clean(title)
        if text:
            draw = ImageDraw.Draw(img)
            size = max(40, int(W * 0.11))             # ~118px on a 1080-wide frame
            font = _font(size)
            margin = int(W * 0.07)
            lines = _wrap(draw, text, font, W - 2 * margin, max_lines=3)
            line_h = int(size * 1.2)
            stroke = max(3, size // 16)
            y = int(H * 0.12)                         # UPPER third (clear of lower-third captions)
            for ln in lines:
                w = draw.textlength(ln, font=font)
                draw.text(((W - w) / 2, y), ln, font=font, fill="white",
                          stroke_width=stroke, stroke_fill="black")
                y += line_h

        img.save(out, "JPEG", quality=88)
        if out.stat().st_size > 2_000_000:            # YouTube thumbnail hard limit is 2MB
            img.resize((W // 2, H // 2)).save(out, "JPEG", quality=85)
        try:
            frame.unlink()
        except Exception:
            pass
        return out
    except Exception as e:
        print(f"    [thumbnail] skipped ({type(e).__name__}: {e})")
        return None
