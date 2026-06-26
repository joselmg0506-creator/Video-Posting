"""
Face-tracking "smart crop" for 16:9 -> 9:16.

A static center-crop cuts off a streamer who's off to one side (you get an arm, not a face).
This finds the main speaker's face across the clip with OpenCV's YuNet detector (CPU) and
slides the crop window horizontally to keep them centered — so they stay big AND in frame.

Returns an ffmpeg `crop` x-expression that follows the face. Degrades gracefully to None
(caller falls back to the static center-crop) when OpenCV / the model / faces aren't available
or the clip isn't landscape. The YuNet model (~340KB) downloads once to data/models/.
"""
import urllib.request
from pathlib import Path

_YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
              "face_detection_yunet/face_detection_yunet_2023mar.onnx")
_MODEL = Path("data/models/face_detection_yunet_2023mar.onnx")
_DET_W = 480   # downscale width for detection (speed); coords scaled back to source


def _ensure_model() -> bool:
    if _MODEL.exists():
        return True
    try:
        _MODEL.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(_YUNET_URL, _MODEL)
        return _MODEL.exists()
    except Exception as e:
        print(f"    [facetrack] model download failed: {e}")
        return False


def track_crop_x(src: Path, start: float, duration: float, sample_fps: float = 4.0,
                 zoom: float = 1.0):
    """Return (x_expr, crop_w, width, height) for an ffmpeg crop=...:x=<expr> that follows the
    main face, or None if face-tracking isn't possible (no cv2 / no faces / not landscape).

    `zoom` controls how tight the crop is: 1.0 = the tightest full-height 9:16 slice (subject
    fills the frame). Lower values crop a WIDER region around the face (e.g. 0.8 ~ 25% wider) so
    you see more of the scene — the caller blur-pads that wider region into the 9:16 frame."""
    try:
        import cv2
    except Exception:
        return None
    if not _ensure_model():
        return None

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return None
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if W <= 0 or H <= 0 or W <= H:           # only landscape clips have something to track
        cap.release()
        return None
    crop_w = min(W, round(H * 9 / 16 / max(0.1, zoom)))   # zoom<1 -> wider view around the face
    if crop_w >= W:                          # already ~vertical/square — nothing to slide
        cap.release()
        return None

    scale = _DET_W / W
    det_h = max(1, round(H * scale))
    try:
        det = cv2.FaceDetectorYN.create(str(_MODEL), "", (_DET_W, det_h), 0.6, 0.3, 5000)
    except Exception as e:
        print(f"    [facetrack] detector init failed: {e}")
        cap.release()
        return None

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / sample_fps)))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start) * 1000.0)

    samples: list[tuple[float, float | None]] = []   # (t_rel, face_center_x in source px)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t_rel = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 - start
        if t_rel > duration + 0.1:
            break
        if idx % step == 0:
            cx = None
            try:
                small = cv2.resize(frame, (_DET_W, det_h))
                _, faces = det.detect(small)
                if faces is not None and len(faces):
                    f = max(faces, key=lambda r: r[2] * r[3])   # largest face = main subject
                    cx = float(f[0] + f[2] / 2) / scale          # back to source px
            except Exception:
                cx = None
            samples.append((max(0.0, t_rel), cx))
        idx += 1
    cap.release()

    if not samples or all(c is None for _, c in samples):
        return None

    # forward/back fill gaps (face briefly not detected -> hold last/next known position)
    last = None
    for i, (t, cx) in enumerate(samples):
        if cx is None:
            samples[i] = (t, last)
        else:
            last = cx
    first = next(c for _, c in samples if c is not None)
    ts = [t for t, _ in samples]
    raw = [(c if c is not None else first) for _, c in samples]

    # EMA smooth, then clamp pan velocity so it glides instead of snapping
    alpha = 0.25
    sm = [raw[0]]
    for x in raw[1:]:
        sm.append(alpha * x + (1 - alpha) * sm[-1])
    max_v = W * 0.6   # px/sec
    for i in range(1, len(sm)):
        dt = max(1e-3, ts[i] - ts[i - 1])
        dx = sm[i] - sm[i - 1]
        lim = max_v * dt
        sm[i] = sm[i - 1] + max(-lim, min(lim, dx))

    # face center -> crop left-x, clamped to frame bounds
    xs = [min(max(cx - crop_w / 2, 0.0), float(W - crop_w)) for cx in sm]

    # downsample to ~2 keypoints/sec to keep the ffmpeg expression compact
    kt, kx = [ts[0]], [xs[0]]
    for i in range(1, len(ts)):
        if ts[i] - kt[-1] >= 0.45 or i == len(ts) - 1:
            kt.append(ts[i])
            kx.append(xs[i])

    # piecewise-linear x(t) expression (single-quoted in the ffmpeg crop filter)
    expr = f"{kx[-1]:.0f}"
    for i in range(len(kt) - 1, 0, -1):
        t0, t1, x0, x1 = kt[i - 1], kt[i], kx[i - 1], kx[i]
        slope = (x1 - x0) / (t1 - t0) if t1 > t0 else 0.0
        expr = f"if(lt(t,{t1:.2f}),({x0:.0f}+({slope:.1f})*(t-{t0:.2f})),{expr})"

    return expr, crop_w, W, H
