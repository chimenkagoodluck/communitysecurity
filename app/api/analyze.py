"""Upload-and-analyze endpoints: image (BLOCK 1) and video (BLOCK 4).

POST /api/analyze/image  — multipart upload, runs analyze_frame, returns the
annotated image (base64 data URL) + a detection list + summary.
POST /api/analyze/video  — multipart upload, samples every Nth frame, annotates,
writes a browser-playable (H.264) MP4, returns a detection timeline.
"""
import base64
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from app.api.auth import get_current_user
from app.config import PROJECT_ROOT, settings
from app.ml.detect import analyze_frame
from app.ml.fire import FireDetector
from app.models import User

router = APIRouter()

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_MEDIA_DIR = PROJECT_ROOT / "data" / "analyzed"
_FFMPEG = shutil.which("ffmpeg")


def _max_severity(severities) -> str | None:
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, -1), default=None)


def _summarize(detections: list[dict]) -> dict:
    harmful = [d for d in detections if d["harmful"]]
    return {
        "total": len(detections),
        "harmful": len(harmful),
        "max_severity": _max_severity(d["severity"] for d in detections),
        "classes": sorted({d["class"] for d in detections}),
    }


@router.post("/image")
async def analyze_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image — upload a JPG or PNG.")

    # Fresh fire detector per request so single-image state never leaks between uploads.
    annotated, detections = analyze_frame(frame, fire_detector=FireDetector())

    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode annotated image")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")

    return {
        "filename": file.filename,
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "annotated_image": f"data:image/jpeg;base64,{b64}",
        "detections": detections,
        "summary": _summarize(detections),
    }


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _transcode_h264(src: Path, dst: Path) -> bool:
    """Transcode mp4v -> browser-playable H.264. Returns True on success."""
    if not _FFMPEG:
        return False
    try:
        r = subprocess.run(
            [_FFMPEG, "-y", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(dst)],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            return True
        logger.warning(f"ffmpeg transcode failed (rc={r.returncode}): {r.stderr[-300:]}")
    except Exception as exc:
        logger.warning(f"ffmpeg transcode error: {exc}")
    return False


def _process_video(in_path: str, out_id: str) -> dict:
    """Sample every Nth frame, annotate, write an MP4, and build a timeline."""
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="Could not open video — try MP4/AVI/MOV.")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if src_fps <= 0:
        src_fps = 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    stride = max(1, round(src_fps / max(settings.VIDEO_ANALYZE_FPS, 1)))
    max_src_frames = int(settings.VIDEO_MAX_SECONDS * src_fps)
    out_fps = max(1, settings.VIDEO_ANALYZE_FPS)

    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_mp4v = _MEDIA_DIR / f"{out_id}_mp4v.mp4"
    writer = cv2.VideoWriter(str(tmp_mp4v), cv2.VideoWriter_fourcc(*"mp4v"),
                             float(out_fps), (width, height))

    fire = FireDetector()  # stateful across the video for flicker-based fire scoring
    timeline: list[dict] = []
    all_severities: list[str] = []
    class_totals: dict[str, int] = {}
    sampled = 0
    idx = 0
    truncated = False

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx >= max_src_frames:
                truncated = True
                break
            if idx % stride == 0:
                annotated, dets = analyze_frame(frame, fire_detector=fire)
                writer.write(annotated)
                sampled += 1
                t = idx / src_fps
                for d in dets:
                    class_totals[d["class"]] = class_totals.get(d["class"], 0) + 1
                    all_severities.append(d["severity"])
                if dets:
                    label = "+".join(sorted({d["class"] for d in dets}))
                    harmful = any(d["harmful"] for d in dets)
                    sev = _max_severity(d["severity"] for d in dets)
                    # Collapse consecutive identical labels into one timeline entry.
                    if timeline and timeline[-1]["label"] == label:
                        timeline[-1]["t_end"] = round(t, 2)
                    else:
                        timeline.append({
                            "t": round(t, 2), "t_end": round(t, 2), "time": _fmt_ts(t),
                            "label": label, "harmful": harmful, "severity": sev,
                        })
            idx += 1
    finally:
        writer.release()
        cap.release()

    # Transcode to browser-playable H.264; fall back to the mp4v file if ffmpeg is absent.
    final_path = _MEDIA_DIR / f"{out_id}.mp4"
    if _transcode_h264(tmp_mp4v, final_path):
        tmp_mp4v.unlink(missing_ok=True)
        video_name = final_path.name
        playable = True
    else:
        video_name = tmp_mp4v.name
        playable = bool(_FFMPEG)  # mp4v may not play in all browsers

    return {
        "video_url": f"/media/{video_name}",
        "browser_playable": playable,
        "timeline": timeline,
        "summary": {
            "frames_sampled": sampled,
            "source_fps": round(src_fps, 2),
            "analyze_fps": out_fps,
            "duration_processed": _fmt_ts(idx / src_fps),
            "truncated": truncated,
            "max_severity": _max_severity(all_severities),
            "detections_by_class": class_totals,
        },
    }


@router.post("/video")
async def analyze_video(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    suffix = Path(file.filename or "").suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}:
        raise HTTPException(status_code=400, detail=f"Unsupported video type: {suffix}")

    out_id = uuid.uuid4().hex[:12]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file")
        tmp.write(data)
        tmp.close()
        # cv2 + ffmpeg are blocking — run off the event loop.
        result = await run_in_threadpool(_process_video, tmp.name, out_id)
        result["filename"] = file.filename
        return result
    finally:
        Path(tmp.name).unlink(missing_ok=True)
