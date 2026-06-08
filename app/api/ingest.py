
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db import get_db
from app.ingest.worker import all_workers_status, start_worker, stop_worker, worker_status
from app.models import Source, User

router = APIRouter()


@router.post("/start/{source_id}")
def start_ingest(source_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    src = db.query(Source).filter(Source.id == source_id).first()
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    started = start_worker(source_id)
    return {"source_id": source_id, "status": worker_status(source_id), "newly_started": started}


@router.post("/stop/{source_id}")
def stop_ingest(source_id: str, _: User = Depends(get_current_user)):
    requested = stop_worker(source_id)
    return {"source_id": source_id, "stop_requested": requested, "status": worker_status(source_id)}


@router.get("/status")
def ingest_status(_: User = Depends(get_current_user)):
    return {"workers": all_workers_status()}
