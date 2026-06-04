"""
Append a short "Subscribe & Like" end card to a finished video.

The card is a plain colored frame with centered text (no narration). We concat it onto
the body with everything normalized to 1080x1920 / 30fps / stereo 44.1k so the join is
clean regardless of the source clip's framerate or channel layout.

ffmpeg runs with cwd set to a temp dir so the subtitles filter can reference the .ass by
bare filename (sidesteps Windows path-escaping).
"""
import subprocess
import tempfile
from pathlib import Path


def _card_ass(text: str, subtext: str, duration: float, font_size: int) -> str:
    end_cs = max(int(duration * 100), 50)
    end = f"0:00:{end_cs // 100:02d}.{end_cs % 100:02d}"
    body = text.replace("{", "(").replace("}", ")").strip()
    if subtext.strip():
        body += "\\N" + subtext.replace("{", "(").replace("}", ")").strip()
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H00000000,"
        "1,0,0,0,100,100,0,0,1,5,2,5,60,60,60,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,{end},Default,,0,0,0,,{body}\n"
    )


def append(
    body: Path,
    out: Path,
    text: str = "SUBSCRIBE & LIKE",
    subtext: str = "",
    duration: float = 2.0,
    font_size: int = 96,
    bg: str = "black",
) -> Path:
    body = Path(body).resolve()
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vp_endcard_") as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "card.ass").write_text(_card_ass(text, subtext, duration, font_size), encoding="utf-8")

        # Normalize both segments to the same v/a params, then concat.
        fc = (
            "[0:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p[b0];"
            "[0:a]aresample=44100,aformat=channel_layouts=stereo:sample_fmts=fltp[b0a];"
            "[1:v]subtitles=card.ass,fps=30,setsar=1,format=yuv420p[c0];"
            "[2:a]aresample=44100,aformat=channel_layouts=stereo:sample_fmts=fltp[c0a];"
            "[b0][b0a][c0][c0a]concat=n=2:v=1:a=1[v][a]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(body),
            "-f", "lavfi", "-i", f"color=c={bg}:s=1080x1920:r=30:d={duration}",
            "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=44100:cl=stereo",
            "-filter_complex", fc,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            str(out),
        ]
        proc = subprocess.run(cmd, cwd=str(tmp_dir), capture_output=True)
        if proc.returncode != 0:
            tail = proc.stderr.decode("utf-8", "ignore")[-2000:]
            raise RuntimeError(f"end card append failed:\n{tail}")

    return out
