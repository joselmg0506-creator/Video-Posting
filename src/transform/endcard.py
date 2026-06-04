"""
Loop-back outro + tiny corner CTA.

Instead of a hard "Subscribe" page (which signals "video over" and kills the rewatch/loop
signal — the strongest 2026 distribution signal), we:
  - echo the OPENING frame for ~0.5s at the end so autoplay replay feels seamless, and
  - keep a small persistent "SUBSCRIBE" tag in a top corner as a low-friction CTA.

Two passes: grab frame 0 as a still, then concat [body][0.5s freeze of frame 0] with the
corner CTA burned over everything. All segments normalized to 1080x1920 / 30fps / stereo
44.1k so the concat is clean regardless of the source clip.
"""
import subprocess
import tempfile
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "ignore")[-2000:]
        raise RuntimeError(f"end card / loop-back failed:\n{tail}")


def _cta_ass(text: str, font: int) -> str:
    safe = text.replace("{", "(").replace("}", ")").replace("\n", " ").strip()
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Small yellow tag, top-right (Alignment 9), clear of the center hook + bottom UI.
        f"Style: CTA,Arial,{font},&H0000FFFF,&H00000000,&H64000000,"
        "1,0,0,0,100,100,0,0,1,3,1,9,40,40,300,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,9:59:59.00,CTA,,0,0,0,,{safe}\n"
    )


def append(
    body: Path,
    out: Path,
    cta_text: str = "SUBSCRIBE",
    loop_seconds: float = 0.5,
    cta_font: int = 46,
) -> Path:
    body = Path(body).resolve()
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vp_loopback_") as tmp:
        tmp_dir = Path(tmp)
        frame0 = tmp_dir / "frame0.png"
        _run(["ffmpeg", "-y", "-i", str(body), "-frames:v", "1", "-update", "1", str(frame0)])
        (tmp_dir / "cta.ass").write_text(_cta_ass(cta_text, cta_font), encoding="utf-8")

        fc = (
            "[0:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p[bv];"
            "[0:a]aresample=44100,aformat=channel_layouts=stereo:sample_fmts=fltp[ba];"
            "[1:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p[fv];"
            "[2:a]aresample=44100,aformat=channel_layouts=stereo:sample_fmts=fltp[fa];"
            "[bv][ba][fv][fa]concat=n=2:v=1:a=1[cv][ca];"
            "[cv]subtitles=cta.ass[outv]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(body),
            "-loop", "1", "-t", str(loop_seconds), "-i", str(frame0),
            "-f", "lavfi", "-t", str(loop_seconds), "-i", "anullsrc=r=44100:cl=stereo",
            "-filter_complex", fc,
            "-map", "[outv]", "-map", "[ca]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            str(out),
        ]
        _run(cmd, cwd=str(tmp_dir))

    return out
