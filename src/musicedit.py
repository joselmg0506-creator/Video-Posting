"""
Music-edit mode: a beat-synced montage — a song over b-roll cut on the beat.

Matches the IShowSpeed-World-Cup-edit style: his own celebration footage (from the music
video) INTERCUT with iconic World Cup moments, full-bleed crop-to-fill, fast beat cuts, a
punchy color grade, and a hook banner. Separate from the clip pipeline.

NOTE: World Cup footage is FIFA's and the song is the label's — expect Content-ID claims /
no monetization. Best kept for-fun / unlisted.

    python main.py --music-edit
"""
import random
import subprocess
import tempfile
from pathlib import Path

import yt_dlp

from .processor.video import _build_filter, _duration
from .transform import compose as _compose


def _download(url: str, out_base: Path, max_seconds: int | None = None) -> Path:
    """Download a video (<=720p mp4). If max_seconds, only grab the first chunk."""
    out_base.parent.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(out_base) + ".%(ext)s",
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    if max_seconds:
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(0, max_seconds)])
        opts["force_keyframes_at_cuts"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    return out_base.with_suffix(".mp4")


def _extract_wav(video: Path, dest: Path) -> Path:
    """Decode a video's audio to wav (for librosa beat tracking + the final mux)."""
    wav = dest.with_suffix(".wav")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "2", "-ar", "44100", str(wav)],
                   check=True, capture_output=True)
    return wav


def _beats(wav: Path, start: float, duration: float) -> list[float]:
    """Beat times (seconds, relative to `start`) within the song window."""
    import librosa
    y, sr = librosa.load(str(wav), sr=22050, offset=start, duration=duration, mono=True)
    _tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
    return [float(t) for t in librosa.frames_to_time(frames, sr=sr)]


def _cut_points(beats: list[float], duration: float, beats_per_cut: int) -> list[float]:
    pts = [0.0] + [b for i, b in enumerate(beats) if i % beats_per_cut == 0 and 0.0 < b < duration]
    pts.append(duration)
    out: list[float] = []
    for p in sorted(set(round(x, 3) for x in pts)):
        if not out or p - out[-1] >= 0.2:      # no segment shorter than ~0.2s
            out.append(p)
    if out[-1] < duration:
        out.append(duration)
    return out


def _segment(broll: Path, seg_len: float, out: Path, fit: str = "crop") -> None:
    """Extract a random `seg_len` window from a b-roll file, crop-to-fill 9:16, color-punched, silent."""
    dur = _duration(broll) or 0
    start = random.uniform(5, max(6, dur - seg_len - 5)) if dur > seg_len + 12 else 0.0
    vf = _build_filter(1080, 1920, fit) + ",eq=contrast=1.04:saturation=1.3"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{seg_len:.2f}", "-i", str(broll),
         "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30", "-pix_fmt", "yuv420p",
         str(out)],
        check=True, capture_output=True,
    )


def make(cfg: dict) -> Path:
    mc = cfg["music_edit"]
    work = Path(cfg["paths"]["downloads"]) / "musicedit"
    broll_dir = Path(mc.get("broll_dir", "./data/broll"))
    out = Path(cfg["paths"]["processed"]) / "music_edit.mp4"
    duration = float(mc.get("duration", 30))
    song_start = float(mc.get("song_start", 0))
    bpc = int(mc.get("beats_per_cut", 2))
    fit = mc.get("fit", "crop")

    print("  fetching song video…")
    song_video = broll_dir / "speed_song.mp4"
    if not song_video.exists():
        song_video = _download(mc["song_url"], broll_dir / "speed_song")
    song_wav = _extract_wav(song_video, work / "song")

    print("  fetching b-roll…")
    brolls: list[Path] = []
    for i, url in enumerate(mc["broll_urls"]):
        f = broll_dir / f"broll_{i}.mp4"
        if not f.exists():
            f = _download(url, broll_dir / f"broll_{i}", max_seconds=int(mc.get("broll_max_seconds", 240)))
        brolls.append(f)
    if not brolls:
        raise RuntimeError("no b-roll downloaded")
    # Intercut Speed's own footage with the World Cup b-roll (weight him so he recurs).
    pool = brolls + [song_video] * max(1, len(brolls) // 2 + 1)

    print("  detecting beats…")
    beats = _beats(song_wav, song_start, duration)
    cuts = _cut_points(beats, duration, bpc)
    print(f"    {len(beats)} beats -> {len(cuts) - 1} cuts")

    with tempfile.TemporaryDirectory(prefix="vp_music_") as tmp:
        tmp_dir = Path(tmp)
        seg_files = []
        for j in range(len(cuts) - 1):
            seg = tmp_dir / f"seg_{j:03d}.mp4"
            _segment(random.choice(pool), cuts[j + 1] - cuts[j], seg, fit=fit)
            seg_files.append(seg)

        listf = tmp_dir / "list.txt"
        listf.write_text("".join(f"file '{s.as_posix()}'\n" for s in seg_files), encoding="utf-8")
        montage = tmp_dir / "montage.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                        "-c", "copy", str(montage)], check=True, capture_output=True)

        with_song = tmp_dir / "with_song.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(montage), "-ss", f"{song_start:.2f}", "-t", f"{duration:.2f}",
             "-i", str(song_wav), "-map", "0:v", "-map", "1:a", "-shortest",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(with_song)],
            check=True, capture_output=True,
        )

        _compose.compose(video=with_song, out=out, voiceover=None,
                         hook_text=mc.get("hook_text", ""), captions_text=None)

    print(f"  done -> {out}")
    return out
