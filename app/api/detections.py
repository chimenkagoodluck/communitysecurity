
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.geo import dbscan, haversine_m
from app.models import Detection, Source, User

router = APIRouter()


_HARMFUL_CLASSES = {"gun", "pistol", "rifle", "weapon", "knife", "machete",
                    "fire", "armed-person"}


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
    minutes: int = Query(default=None, ge=1, le=10080),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
   
    if minutes is None:
        minutes = settings.HOTSPOT_WINDOW_HOURS * 60
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

   
    rows = (
        db.query(
            Detection.lat, Detection.lon, Detection.threat_class,
            func.count(Detection.id).label("n"),
            func.max(Detection.confidence).label("max_conf"),
        )
        .filter(Detection.detected_at >= cutoff)
        .filter(Detection.lat.isnot(None)).filter(Detection.lon.isnot(None))
        .group_by(Detection.lat, Detection.lon, Detection.threat_class)
        .all()
    )

   
    locations: dict[tuple, dict] = {}
    total = 0
    for r in rows:
        total += r.n
        key = (r.lat, r.lon)
        loc = locations.setdefault(
            key, {"lat": r.lat, "lon": r.lon, "count": 0,
                  "classes": Counter(), "max_conf": 0.0}
        )
        loc["count"] += r.n
        loc["classes"][r.threat_class] += r.n
        loc["max_conf"] = max(loc["max_conf"], r.max_conf or 0.0)

    locs = list(locations.values())
    pts = [(l["lat"], l["lon"]) for l in locs]
    wts = [l["count"] for l in locs]
    labels = dbscan(pts, settings.HOTSPOT_EPS_METERS,
                    settings.HOTSPOT_MIN_SAMPLES, weights=wts) if pts else []

    grouped: dict[int, list] = {}
    for loc, lab in zip(locs, labels):
        if lab >= 0:
            grouped.setdefault(lab, []).append(loc)

    clusters = []
    for members in grouped.values():
        count = sum(m["count"] for m in members)
        # Detection-count-weighted centroid.
        clat = sum(m["lat"] * m["count"] for m in members) / count
        clon = sum(m["lon"] * m["count"] for m in members) / count
        radius = max((haversine_m(clat, clon, m["lat"], m["lon"]) for m in members), default=0.0)
        class_counts: Counter = sum((m["classes"] for m in members), Counter())
        clusters.append({
            "lat": round(clat, 6),
            "lon": round(clon, 6),
            "count": count,
            "radius_m": round(radius, 1),
            "top_class": class_counts.most_common(1)[0][0],
            "classes": dict(class_counts),
            "harmful": any(c in _HARMFUL_CLASSES for c in class_counts),
            "max_confidence": round(max(m["max_conf"] for m in members), 3),
        })
    clusters.sort(key=lambda c: c["count"], reverse=True)

   
    max_count = max((l["count"] for l in locs), default=1) or 1
    heat = [[round(l["lat"], 6), round(l["lon"], 6),
             round(max(0.15, (l["count"] / max_count) ** 0.5), 3)] for l in locs]

    return {
        "params": {
            "window_minutes": minutes,
            "eps_meters": settings.HOTSPOT_EPS_METERS,
            "min_samples": settings.HOTSPOT_MIN_SAMPLES,
        },
        "clusters": clusters,
        "heat": heat,
        "noise": sum(1 for lab in labels if lab < 0),
        "locations": len(locs),
        "total": total,
    }
