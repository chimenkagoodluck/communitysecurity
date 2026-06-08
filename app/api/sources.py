
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.ingest.frame_store import get_frame, has_recent_frame
from app.ingest.worker import worker_status as _worker_status
from app.ingest.source import VideoSource, normalize_locator
from app.models import Source, SourceCategory, SourceKind, SourceStatus, User
from app.schemas import SourceCreate, SourceOut

router = APIRouter()


@router.get("/", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Source).order_by(Source.created_at.desc()).all()


@router.post("/", response_model=SourceOut, status_code=201)
def create_source(
    payload: SourceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        kind = SourceKind(payload.kind)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid kind")
    try:
        category = SourceCategory(payload.category)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category")

    source = Source(
        name=payload.name, description=payload.description,
        kind=kind, category=category, locator=normalize_locator(payload.locator),
        location_lat=payload.location_lat, location_lon=payload.location_lon,
        location_label=payload.location_label,
        drone_model=payload.drone_model, cctv_vendor=payload.cctv_vendor,
        altitude_m=payload.altitude_m, has_ptz=payload.has_ptz,
        notes=payload.notes,
    )
    db.add(source); db.commit(); db.refresh(source)
    return source


@router.get("/{source_id}", response_model=SourceOut)
def get_source(source_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    src = db.query(Source).filter(Source.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


@router.post("/{source_id}/probe")
def probe_source(
    source_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.ingest.worker import worker_status
    src = db.query(Source).filter(Source.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    if worker_status(source_id) == "running":
        return {
            "ok": True, "kind": src.kind.value, "locator": src.locator,
            "note": "Worker is streaming — probe skipped to avoid double-open",
            "native_fps": None, "width": None, "height": None, "resolution": None,
        }
    vs = VideoSource.from_model(src)
    info = vs.probe()
    
    src.last_error = None if info.get("ok") else info.get("error")
    db.commit()
    return info


@router.delete("/{source_id}", status_code=204)
def delete_source(
    source_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user),
):
    src = db.query(Source).filter(Source.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete(src); db.commit()


@router.get("/{source_id}/stream.mjpeg")
def stream_mjpeg(
    source_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Live MJPEG stream. Returns multipart/x-mixed-replace which browsers render
    as an animated <img>. The actual frames come from the in-memory frame store
    written by the ingestion worker. If no worker is running for this source,
    a "No Signal" placeholder is served at the same FPS so the <img> never breaks.
    """
    src = db.query(Source).filter(Source.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    boundary = "cssa-frame-boundary"
    frame_period = 1.0 / max(settings.STREAM_FPS, 1)

    def gen():
        try:
            while True:
                running = _worker_status(source_id) == "running"
                jpeg = get_frame(source_id, worker_running=running)
                if jpeg:
                    yield (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode("utf-8") + jpeg + b"\r\n"
                time.sleep(frame_period)
        except GeneratorExit:
            pass  # client disconnected — stop cleanly

    return StreamingResponse(
        gen(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/{source_id}/status")
def source_status(source_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Lightweight status for the source-detail page polling."""
    src = db.query(Source).filter(Source.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    return {
        "id": src.id,
        "status": src.status.value,
        "has_live_frame": has_recent_frame(source_id),
        "last_frame_at": src.last_frame_at.isoformat() if src.last_frame_at else None,
        "last_error": src.last_error,
    }
