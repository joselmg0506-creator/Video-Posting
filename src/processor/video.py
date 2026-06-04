import re
import subprocess
from pathlib import Path


def _duration(src: Path) -> float | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(src)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def _find_peak(src: Path) -> float | None:
    """Time (s) of the loudest ~1s window — the highlight. None if it can't be measured."""
    try:
        af = (
            "aresample=16000,asetnsamples=n=16000,astats=metadata=1:reset=1,"
            "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level"
        )
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af", af, "-f", "null", "-"],
            capture_output=True, text=True, errors="ignore",
        )
        text = proc.stderr     # ametadata print goes to the log (stderr)

        best_t, best_rms, cur_t = None, float("-inf"), None
        for line in text.splitlines():
            m = re.search(r"pts_time:([0-9.]+)", line)
            if m:
                cur_t = float(m.group(1))
                continue
            m = re.search(r"RMS_level=(-?[0-9.]+)", line)   # skips "-inf" (silence)
            if m and cur_t is not None:
                rms = float(m.group(1))
                if rms > best_rms:
                    best_rms, best_t = rms, cur_t
        return best_t
    except Exception:
        return None


def _peak_start(src: Path, max_duration: int) -> float:
    """Where to start the cut so the clip cold-opens on the highlight (a short lead-in
    before the loudest moment). 0 if the clip is shorter than the window or has no peak."""
    dur = _duration(src)
    if not dur or dur <= max_duration:
        return 0.0
    peak = _find_peak(src)
    if peak is None:
        return 0.0
    lead = min(2.0, 0.15 * max_duration)
    return max(0.0, min(peak - lead, dur - max_duration))


def _build_filter(width: int, height: int, fit: str) -> str:
    """Build an ffmpeg filtergraph that fits arbitrary input into width x height."""
    if fit == "crop":
        # scale so the shorter side fills, then center-crop
        return (
            f"scale=if(gt(a\\,{width}/{height})\\,-2\\,{width}):"
            f"if(gt(a\\,{width}/{height})\\,{height}\\,-2),"
            f"crop={width}:{height}"
        )
    if fit == "letterbox":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    # blur_pad (default): blurred fill behind the contained video
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=20:5[bg2];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2"
    )


def process(
    src: Path,
    dest: Path,
    width: int = 1080,
    height: int = 1920,
    fit: str = "blur_pad",
    max_duration: int = 60,
    peak_trim: bool = True,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Cold-open on the highlight instead of the clip's first seconds.
    start = _peak_start(src, max_duration) if peak_trim else 0.0
    vf = _build_filter(width, height, fit)
    # blur_pad uses -filter_complex; others use -vf
    filter_flag = "-filter_complex" if fit == "blur_pad" else "-vf"
    cmd = ["ffmpeg", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.2f}"]      # input seek (fast) to the peak window
    cmd += [
        "-i", str(src),
        "-t", str(max_duration),
        filter_flag, vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest
