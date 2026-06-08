from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_db
from app.models import Alert, AlertStatus, User

router = APIRouter()


@router.get("/")
def list_alerts(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    minutes: int = Query(1440, ge=1, le=10080),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    q = db.query(Alert).filter(Alert.dispatched_at >= cutoff)
    if severity:
        q = q.filter(Alert.severity == severity)
    if status:
        q = q.filter(Alert.status == status)
    rows = q.order_by(Alert.dispatched_at.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "severity": a.severity.value if hasattr(a.severity, "value") else a.severity,
            "status": a.status.value if hasattr(a.status, "value") else a.status,
            "title": a.title,
            "message": a.message,
            "lat": a.lat,
            "lon": a.lon,
            "dispatched_at": a.dispatched_at.isoformat(),
            "source_id": a.source_id,
            "detection_id": a.detection_id,
        } for a in rows
    ]


@router.post("/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    a = db.query(Alert).filter(Alert.id == alert_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Alert not found")
    a.status = AlertStatus.acknowledged
    a.acknowledged_by = user.id
    a.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": a.id, "status": a.status.value}


@router.get("/summary")
def alert_summary(
    minutes: int = Query(1440, ge=1, le=10080),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from sqlalchemy import func
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = (
        db.query(Alert.severity, func.count(Alert.id))
        .filter(Alert.dispatched_at >= cutoff)
        .group_by(Alert.severity).all()
    )
    by_sev = {sev.value if hasattr(sev, "value") else sev: int(cnt) for (sev, cnt) in rows}
    return {
        "window_minutes": minutes,
        "by_severity": by_sev,
        "total": sum(by_sev.values()),
        "new": db.query(Alert).filter(
            Alert.dispatched_at >= cutoff, Alert.status == AlertStatus.new
        ).count(),
    }
