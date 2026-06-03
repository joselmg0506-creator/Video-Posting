import subprocess
from pathlib import Path


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
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = _build_filter(width, height, fit)
    # blur_pad uses -filter_complex; others use -vf
    filter_flag = "-filter_complex" if fit == "blur_pad" else "-vf"
    cmd = [
        "ffmpeg",
        "-y",
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
