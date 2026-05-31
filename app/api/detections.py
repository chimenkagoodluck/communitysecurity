"""Detection listing + filtering."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_db
from app.models import Detection, Source, User

router = APIRouter()


@router.get("/")
def list_detections(
    source_id: Optional[str] = None,
    threat_class: Optional[str] = None,
    minutes: int = Query(60, ge=1, le=10080),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    q = db.query(Detection).filter(Detection.detected_at >= cutoff)
    if source_id:
        q = q.filter(Detection.source_id == source_id)
    if threat_class:
        q = q.filter(Detection.threat_class == threat_class)
    rows = q.order_by(Detection.detected_at.desc()).limit(limit).all()

    return [
        {
            "id": r.id, "source_id": r.source_id,
            "detected_at": r.detected_at.isoformat(),
            "model_source": r.model_source.value if hasattr(r.model_source, "value") else r.model_source,
            "threat_class": r.threat_class, "confidence": r.confidence,
            "spatial_score": r.spatial_score, "temporal_score": r.temporal_score,
            "fused_score": r.fused_score, "bbox": r.bbox,
            "lat": r.lat, "lon": r.lon,
        } for r in rows
    ]


@router.get("/summary")
def summary(
    minutes: int = Query(60, ge=1, le=10080),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = (
        db.query(Detection.threat_class, func.count(Detection.id))
        .filter(Detection.detected_at >= cutoff)
        .group_by(Detection.threat_class).all()
    )
    return {"window_minutes": minutes, "counts": dict(rows)}


@router.get("/hotspots")
def hotspots(
    minutes: int = Query(360, ge=1, le=10080),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Returns rough hotspot points (no DBSCAN yet — that's Day 4).
    For now we group by source location and return weighted points for a heatmap.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = (
        db.query(Detection.lat, Detection.lon, func.count(Detection.id).label("n"))
        .filter(Detection.detected_at >= cutoff)
        .filter(Detection.lat.isnot(None)).filter(Detection.lon.isnot(None))
        .group_by(Detection.lat, Detection.lon).all()
    )
    return [{"lat": lat, "lon": lon, "intensity": int(n)} for (lat, lon, n) in rows]
