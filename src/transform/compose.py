"""
Render the final Short: burn a top hook banner + (optional) captions, and mix the AI
voiceover over the (ducked) clip audio. Deterministic text sizing via an ASS file pinned
to 1080x1920 play-res.

Caption placement is lifted out of the bottom 20-25% where TikTok stacks its like/comment/
share UI, so the same render is safe on both Shorts and TikTok. The hook is a yellow
top-third banner held for the first couple seconds (the sound-off scroll-stopper).

ffmpeg runs with cwd set to a temp dir so the `subtitles=` filter can reference the .ass
by bare filename (sidesteps Windows path-escaping).
"""
import shutil
import subprocess
import tempfile
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "ignore")[-2000:]
        raise RuntimeError(f"ffmpeg failed:\n{tail}")


def _probe_duration(path: Path) -> float | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def _fmt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs >= 100:
        cs = 0
        s += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _chunk(text: str, max_words: int = 5) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)] or [text]


def _safe(s: str) -> str:
    return s.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _phrases(words: list[tuple[str, float, float]], max_words: int = 4, max_gap: float = 0.7):
    """Group word timings into short caption phrases, breaking on length or a speech gap."""
    out: list[list[tuple[str, float, float]]] = []
    cur: list[tuple[str, float, float]] = []
    for w in words:
        if cur and (len(cur) >= max_words or w[1] - cur[-1][2] > max_gap):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def _ass_header(caption_font: int, hook_font: int) -> str:
    # Caption style: Secondary (white) = upcoming word, Primary (yellow) = highlighted word,
    # so \k karaoke pops each word yellow as it's spoken. Lifted to MarginV=520 (clear of UI).
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"          # smart-wrap long lines instead of running off-frame
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Caption,Arial,{caption_font},&H0000FFFF,&H00FFFFFF,&H00000000,&H64000000,"
        "1,0,0,0,100,100,0,0,1,4,1,2,80,80,520,1\n"
        f"Style: Hook,Arial,{hook_font},&H0000FFFF,&H00FFFFFF,&H00000000,&H64000000,"
        "1,0,0,0,100,100,0,0,1,5,2,8,60,60,300,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _build_ass(
    hook_text: str | None,
    hook_dur: float,
    caption_font: int,
    hook_font: int,
    caption_words: list[tuple[str, float, float]] | None = None,
    captions_text: str | None = None,
    captions_dur: float = 0.0,
) -> str:
    events: list[str] = []
    if hook_text:
        events.append(f"Dialogue: 0,{_fmt_ts(0)},{_fmt_ts(hook_dur)},Hook,,0,0,0,,{_safe(hook_text)}")

    if caption_words:
        for phrase in _phrases(caption_words):
            start, end = phrase[0][1], phrase[-1][2] + 0.1
            parts = []
            for j, (word, ws, _we) in enumerate(phrase):
                nxt = phrase[j + 1][1] if j + 1 < len(phrase) else phrase[j][2]
                k = max(1, int(round((nxt - ws) * 100)))     # centiseconds for \k
                parts.append(f"{{\\k{k}}}{_safe(word)} ")
            events.append(
                f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Caption,,0,0,0,,{''.join(parts).strip()}"
            )
    elif captions_text:
        chunks = _chunk(captions_text, 5)
        per = max(captions_dur, 0.5) / len(chunks)
        for i, ch in enumerate(chunks):
            events.append(
                f"Dialogue: 0,{_fmt_ts(i * per)},{_fmt_ts((i + 1) * per)},Caption,,0,0,0,,{_safe(ch)}"
            )

    return _ass_header(caption_font, hook_font) + "\n".join(events) + "\n"


def compose(
    video: Path,
    out: Path,
    voiceover: Path | None = None,
    duck_db: float = -10,
    captions_text: str | None = None,
    caption_words: list[tuple[str, float, float]] | None = None,
    hook_text: str | None = None,
    font_size: int = 64,
    hook_font_size: int = 74,
    hook_duration: float = 2.5,
) -> Path:
    video = Path(video).resolve()
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    voiceover = Path(voiceover).resolve() if voiceover else None

    need_subs = bool(captions_text or caption_words or hook_text)
    if voiceover is None and not need_subs:
        shutil.copyfile(video, out)
        return out

    has_audio = _has_audio(video)
    vdur = _probe_duration(video)
    adur = _probe_duration(voiceover) if voiceover else None

    with tempfile.TemporaryDirectory(prefix="vp_compose_") as tmp:
        tmp_dir = Path(tmp)
        filters: list[str] = []

        # ---- video chain: subtitles, plus freeze-pad if the voiceover outlasts the clip
        vchain: list[str] = []
        if need_subs:
            captions_dur = adur or vdur or max(2.0, len((captions_text or "").split()) / 165 * 60)
            (tmp_dir / "subs.ass").write_text(
                _build_ass(
                    hook_text, hook_duration, font_size, hook_font_size,
                    caption_words=caption_words, captions_text=captions_text,
                    captions_dur=captions_dur,
                ),
                encoding="utf-8",
            )
            vchain.append("subtitles=subs.ass")
        if voiceover and adur and vdur and adur > vdur + 0.05:
            vchain.append(f"tpad=stop_mode=clone:stop_duration={adur - vdur:.2f}")

        if vchain:
            filters.append(f"[0:v]{','.join(vchain)}[vout]")
            vmap = "[vout]"
        else:
            vmap = "0:v"

        # ---- audio: mix ducked original under the voiceover (or whichever exists)
        if voiceover and has_audio:
            filters.append(
                f"[0:a]volume={duck_db}dB[a0];[1:a]volume=2dB[a1];"
                "[a0][a1]amix=inputs=2:duration=longest:normalize=0[aout]"
            )
            amap = "[aout]"
        elif voiceover:
            amap = "1:a"
        elif has_audio:
            amap = "0:a"
        else:
            amap = None

        cmd = ["ffmpeg", "-y", "-i", str(video)]
        if voiceover:
            cmd += ["-i", str(voiceover)]
        if filters:
            cmd += ["-filter_complex", ";".join(filters)]
        cmd += ["-map", vmap]
        if amap:
            cmd += ["-map", amap]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            str(out),
        ]
        _run(cmd, cwd=str(tmp_dir))

    return out
