import re
import subprocess
import tempfile
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


def _score_peak(src: Path) -> float | None:
    """Time (s) of the highest-"excitement" 1s window, combining loudness (RMS) with
    spectral-flux onset strength (spikes on reactions/laughs/hits/SFX) — a better highlight
    cue than loudness alone. z-scores each envelope so neither dominates by raw scale.
    Returns None (→ caller falls back to the plain RMS pass) if librosa isn't usable."""
    try:
        import numpy as np
        import librosa

        sr = 22050
        # Decode to a temp WAV with ffmpeg first: soundfile can't read MP4/AAC (every Twitch
        # clip), so a direct librosa.load would fall back to the slow, deprecated audioread
        # path. A WAV loads natively — faster and warning-free.
        with tempfile.TemporaryDirectory(prefix="vp_peak_") as td:
            wav = Path(td) / "a.wav"
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), str(wav)],
                capture_output=True,
            )
            if r.returncode != 0 or not wav.exists():
                return None
            y, sr = librosa.load(str(wav), sr=sr, mono=True)
        if y.size == 0:
            return None
        hop = 512
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        rms = librosa.feature.rms(y=y, hop_length=hop)[0]
        n = min(len(onset), len(rms))
        if n == 0:
            return None
        onset, rms = onset[:n], rms[:n]
        secs = librosa.frames_to_time(np.arange(n), sr=sr, hop_length=hop).astype(int)
        buckets = sorted(set(secs.tolist()))

        def _bin(env):
            return np.array([env[secs == s].mean() for s in buckets])

        def _z(a):
            sd = a.std()
            return (a - a.mean()) / sd if sd > 1e-9 else np.zeros_like(a)

        score = 1.0 * _z(_bin(onset)) + 0.8 * _z(_bin(rms))
        return float(buckets[int(np.argmax(score))])
    except Exception:
        return None


def _peak_start(src: Path, max_duration: int) -> float:
    """Where to start the cut so the clip cold-opens on the highlight (a short lead-in
    before the peak). 0 if the clip is shorter than the window or has no peak."""
    dur = _duration(src)
    if not dur or dur <= max_duration:
        return 0.0
    peak = _score_peak(src)        # multi-signal (onset+RMS); falls back to plain RMS
    if peak is None:
        peak = _find_peak(src)
    if peak is None:
        return 0.0
    lead = min(2.0, 0.15 * max_duration)
    return max(0.0, min(peak - lead, dur - max_duration))


def _ends_sentence(word: str) -> bool:
    """True if a (whisper) word token ends a sentence — terminal punctuation, ignoring any
    trailing closing quote/bracket the model attached."""
    return word.rstrip("\")'”’").endswith((".", "!", "?"))


def _snap_end(src: Path, start: float, max_duration: int,
              grace: float = 6.0, model: str = "base", language: str = "en") -> float:
    """Choose a cut DURATION that ends on a complete sentence so the clip doesn't stop on a
    cliffhanger. Transcribes the candidate window from `start`, then picks the sentence-ending
    boundary CLOSEST to the target length, allowing up to `grace` extra seconds to finish a
    thought. Best-effort: returns max_duration on no transcript / no boundary / any failure.

    For staged clips this runs at staging time (laptop), so it adds no cloud cost."""
    cap = float(max_duration)
    dur = _duration(src) or 0.0
    win = min(cap + grace, dur - start)
    if win <= cap * 0.5:                      # not enough material to bother snapping
        return cap
    try:
        from ..transform.transcribe import transcribe
        with tempfile.TemporaryDirectory(prefix="vp_snap_") as td:
            wav = Path(td) / "a.wav"
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(src), "-t", f"{win:.2f}",
                 "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                capture_output=True,
            )
            if r.returncode != 0 or not wav.exists():
                return cap
            words = transcribe(wav, model=model, language=language)   # times relative to `start`
    except Exception as e:
        print(f"  [end-snap] skipped ({type(e).__name__}: {e})")
        return cap
    floor = cap * 0.5                         # don't snap to a too-short clip
    ceiling = cap + grace
    ends = [we for (w, _ws, we) in words if _ends_sentence(w) and floor <= we <= ceiling]
    if not ends:
        return cap
    chosen = min(ends, key=lambda e: abs(e - cap))   # sentence end nearest the target length
    print(f"  [end-snap] ending on a sentence at {chosen:.1f}s (cap {int(cap)}s, +{grace:g}s grace)")
    return min(chosen + 0.3, win)            # small tail pad, never past the available window


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
    track_zoom: float = 1.0,
    end_snap: bool = False,
    end_grace: float = 6.0,
    snap_model: str = "base",
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Cold-open on the highlight instead of the clip's first seconds.
    start = _peak_start(src, max_duration) if peak_trim else 0.0

    # End on a complete sentence (no cliffhangers) instead of a hard time cut — only when we're
    # actually slicing a window out of a LONGER source (short curated clips already end cleanly).
    dur = _duration(src) or 0.0
    if end_snap and dur > max_duration:
        length = _snap_end(src, start, max_duration, grace=end_grace, model=snap_model)
    else:
        length = float(max_duration)

    if fit == "track":
        # Smart crop: follow the streamer's face so they stay centered (not cut off). Falls
        # back to a static center-crop when face-tracking isn't available or finds no face.
        tracked = None
        try:
            from .facetrack import track_crop_x
            tracked = track_crop_x(src, start, length, zoom=track_zoom)
        except Exception as e:
            print(f"  [track] face-tracking unavailable ({e}); using center crop")
        if tracked:
            expr, crop_w, W, H = tracked
            if abs(crop_w / H - width / height) < 0.02:
                # tightest 9:16 slice (zoom ~1.0) — clean crop + scale, fills the frame
                vf = (f"crop=w={crop_w}:h={H}:x='{expr}':y=0,"
                      f"scale={width}:{height}:flags=lanczos,setsar=1")
                filter_flag = "-vf"
                print("  [track] following the speaker's face")
            else:
                # wider view (zoom < 1.0): crop a wider region around the face, fit it to width,
                # and blur-pad the top/bottom so you see more of the scene (subject a bit smaller)
                vf = (f"[0:v]crop=w={crop_w}:h={H}:x='{expr}':y=0,split=2[bg][fg];"
                      f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                      f"crop={width}:{height},boxblur=20:5[bg2];"
                      f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos[fg2];"
                      f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1")
                filter_flag = "-filter_complex"
                print(f"  [track] following the speaker's face (wider view, zoom {track_zoom})")
        else:
            vf = _build_filter(width, height, "crop")
            filter_flag = "-vf"
    else:
        vf = _build_filter(width, height, fit)
        # blur_pad uses -filter_complex; others use -vf
        filter_flag = "-filter_complex" if fit == "blur_pad" else "-vf"
    cmd = ["ffmpeg", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.2f}"]      # input seek (fast) to the peak window
    cmd += [
        "-i", str(src),
        "-t", f"{length:.2f}",
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
