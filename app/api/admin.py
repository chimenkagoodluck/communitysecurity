"""Admin: users, system stats, and data management (backup/restore/reset)."""
import os
import platform
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import PROJECT_ROOT, settings
from app.db import Base, engine, get_db
from app.ingest.worker import all_workers_status
from app.models import Alert, Detection, Source, User
from app.schemas import UserOut

router = APIRouter()

_DB_PATH = PROJECT_ROOT / "data" / "cssa.db"
_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
_data_lock = threading.Lock()   # prevents concurrent backup/restore/reset


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.get("/system")
def system_info(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """System health snapshot for the admin page."""
    n_users = db.query(User).count()
    n_sources = db.query(Source).count()
    n_detections = db.query(Detection).count()
    n_alerts = db.query(Alert).count()

    last_hour = datetime.now(timezone.utc) - timedelta(hours=1)
    n_detect_hr = db.query(Detection).filter(Detection.detected_at >= last_hour).count()
    n_alert_hr = db.query(Alert).filter(Alert.dispatched_at >= last_hour).count()

    return {
        "app_name": settings.APP_NAME,
        "app_env": settings.APP_ENV,
        "python_version": platform.python_version(),
        "system": f"{platform.system()} {platform.release()}",
        "counts": {
            "users": n_users,
            "sources": n_sources,
            "detections": n_detections,
            "alerts": n_alerts,
            "detections_last_hour": n_detect_hr,
            "alerts_last_hour": n_alert_hr,
        },
        "workers": all_workers_status(),
        "thresholds": {
            "spatial_confidence": settings.SPATIAL_CONFIDENCE_THRESHOLD,
            "temporal_anomaly": settings.TEMPORAL_ANOMALY_THRESHOLD,
            "fusion_alert": settings.FUSION_ALERT_THRESHOLD,
        },
        "fusion": {
            "alpha": settings.FUSION_ALPHA,
            "beta": settings.FUSION_BETA,
            "gamma": settings.FUSION_GAMMA,
        },
    }


# ── Data Management ──────────────────────────────────────────────────────────

@router.get("/data/backups")
def list_backups(_: User = Depends(get_current_user)):
    """List all database backups ordered newest first."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for f in sorted(_BACKUP_DIR.glob("cssa_*.db"), reverse=True):
        st = f.stat()
        result.append({
            "name": f.name,
            "size_kb": round(st.st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return result


@router.post("/data/backup")
def create_backup(_: User = Depends(get_current_user)):
    """Snapshot the current database to data/backups/."""
    if not _DB_PATH.exists():
        raise HTTPException(status_code=404, detail="No database file found to back up")
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = f"cssa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(_DB_PATH, _BACKUP_DIR / name)
    return {"ok": True, "backup": name}


@router.post("/data/reset")
def reset_database(_: User = Depends(get_current_user)):
    """
    Auto-backup, then wipe ALL data INCLUDING users — the database is left
    completely empty. After this you sign up again at /signup, and the first
    account created becomes the new administrator. No demo data is created.

    Uses SQL DELETE instead of file deletion so the operation works on Windows
    even while the database file is held open by the current request session.
    """
    if not _data_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another data operation is in progress")
    try:
        # 1. Stop all running ingestion workers
        from app.ingest.worker import _workers, _workers_lock
        with _workers_lock:
            for w in list(_workers.values()):
                w.request_stop()
            _workers.clear()

        # 2. Auto-backup before wiping (reading the file is always safe on Windows)
        backup_name = None
        if _DB_PATH.exists():
            _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            backup_name = f"cssa_{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_reset.db"
            shutil.copy2(_DB_PATH, _BACKUP_DIR / backup_name)

        # 3. Wipe all rows via SQL — never touch the file, so Windows file
        #    locks (held by the current request session) are not an issue.
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            for tbl in ("alerts", "detections", "subscribers", "geofences", "sources", "users"):
                conn.execute(text(f"DELETE FROM {tbl}"))
            conn.execute(text("PRAGMA foreign_keys = ON"))

        return {
            "ok": True,
            "message": "Reset complete. The database is empty. Sign up to create the first admin.",
            "redirect": "/signup",
            "auto_backup": backup_name,
        }
    finally:
        _data_lock.release()


@router.post("/data/restore/{backup_name}")
def restore_backup(backup_name: str, _: User = Depends(get_current_user)):
    """
    Restore the database from a backup.
    Auto-saves the current state first so nothing is lost.

    Uses SQLite ATTACH DATABASE to copy rows from the backup file into the
    live database without ever overwriting the locked file on disk — this
    avoids the Windows PermissionError that occurs when a file is in use.
    """
    if not backup_name.endswith(".db") or "/" in backup_name or "\\" in backup_name or ".." in backup_name:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    backup_path = _BACKUP_DIR / backup_name
    if not backup_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    if not _data_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another data operation is in progress")
    try:
        # 1. Stop workers
        from app.ingest.worker import _workers, _workers_lock
        with _workers_lock:
            for w in list(_workers.values()):
                w.request_stop()
            _workers.clear()

        # 2. Backup current state first (read-only copy — safe on Windows)
        pre_backup = None
        if _DB_PATH.exists():
            _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            pre_backup = f"cssa_{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_restore.db"
            shutil.copy2(_DB_PATH, _BACKUP_DIR / pre_backup)

        # 3. Use SQLite ATTACH to copy all rows from the backup into the live
        #    database. This modifies the file contents via SQL rather than
        #    replacing the file, so Windows file locks are not an issue.
        bp = str(backup_path).replace("\\", "/")
        tables = ["users", "sources", "detections", "alerts", "subscribers", "geofences"]
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.execute(text(f"ATTACH DATABASE '{bp}' AS bk"))
            for tbl in tables:
                conn.execute(text(f"DELETE FROM main.{tbl}"))
                try:
                    conn.execute(text(f"INSERT INTO main.{tbl} SELECT * FROM bk.{tbl}"))
                except Exception:
                    pass  # table may not exist in older backups — skip safely
            conn.execute(text("DETACH DATABASE bk"))
            conn.execute(text("PRAGMA foreign_keys = ON"))

        return {
            "ok": True,
            "message": f"Restored from {backup_name}. Refresh and log in again.",
            "pre_restore_backup": pre_backup,
        }
    finally:
        _data_lock.release()


@router.delete("/data/backup/{backup_name}", status_code=204)
def delete_backup(backup_name: str, _: User = Depends(get_current_user)):
    """Delete a specific backup file."""
    if not backup_name.endswith(".db") or "/" in backup_name or "\\" in backup_name or ".." in backup_name:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    p = _BACKUP_DIR / backup_name
    if not p.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    p.unlink()


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Per-class + per-source detection metrics for the admin charts."""
    by_class = dict(
        db.query(Detection.threat_class, func.count(Detection.id))
        .group_by(Detection.threat_class).all()
    )

    by_source_raw = (
        db.query(Source.name, func.count(Detection.id))
        .outerjoin(Detection, Detection.source_id == Source.id)
        .group_by(Source.id).all()
    )
    by_source = {name: int(cnt) for (name, cnt) in by_source_raw}

    by_severity = dict(
        db.query(Alert.severity, func.count(Alert.id))
        .group_by(Alert.severity).all()
    )
    by_severity = {
        (k.value if hasattr(k, "value") else k): int(v) for k, v in by_severity.items()
    }

    return {
        "detections_by_class": by_class,
        "detections_by_source": by_source,
        "alerts_by_severity": by_severity,
    }
