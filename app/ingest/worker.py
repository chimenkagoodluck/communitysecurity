"""
Per-source ingestion worker.

For each frame:
  1. Run YOLOv8 spatial detection
  2. Run fire detection
  3. Persist detections to DB
  4. Annotate the frame with bboxes + labels
  5. Push the annotated JPEG into the frame store (consumed by MJPEG endpoint)
  6. If any high-confidence detection, create an alert
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import cv2
from loguru import logger

from app.config import settings
from app.db import SessionLocal
from app.ingest.frame_store import clear_frame, put_frame
from app.ingest.source import SourceError, VideoSource
from app.ml.fire import FireDetector
from app.ml.yolo import annotate, detect as yolo_detect, SpatialDetection
from app.models import (
    Alert, AlertSeverity, AlertStatus, Detection, ModelSource, Source, SourceStatus,
)

# Threshold above which we auto-create an alert
ALERT_THRESHOLD = {
    "person": 0.85,     # noisy — only very confident
    "vehicle": 0.80,
    "fire": 0.50,
    "bicycle": 0.85,
    "motorcycle": 0.85,
}


class IngestWorker(threading.Thread):
    def __init__(self, source_id: str, target_fps: Optional[int] = None):
        super().__init__(daemon=True, name=f"ingest-{source_id[:8]}")
        self.source_id = source_id
        self.target_fps = target_fps or settings.INGEST_TARGET_FPS
        # NOTE: must NOT be named _stop — threading.Thread has an internal _stop()
        # method in Python 3.11 that is called by join(). Naming our event _stop
        # overwrites that method, causing "TypeError: 'Event' object is not callable"
        # on the second Start (when start_worker calls existing.join()).
        self._shutdown_event = threading.Event()
        self._fire = FireDetector()

    def request_stop(self) -> None:
        self._shutdown_event.set()

    def run(self) -> None:
        logger.info(f"[{self.name}] starting @ {self.target_fps} fps")

        db = SessionLocal()
        try:
            src = db.query(Source).filter(Source.id == self.source_id).first()
            if not src:
                logger.error(f"[{self.name}] source not found"); return
            kind = src.kind.value if hasattr(src.kind, "value") else src.kind
            locator = src.locator
            src.status = SourceStatus.streaming
            src.last_error = None
            db.commit()
        finally:
            db.close()

        try:
            video = VideoSource.from_kind(kind, locator)
            video.open()
        except SourceError as exc:
            logger.error(f"[{self.name}] open failed: {exc}")
            self._set_error(str(exc))
            return

        try:
            self._loop(video)
        finally:
            video.close()
            clear_frame(self.source_id)
            self._set_idle()
            logger.info(f"[{self.name}] stopped")

    def _loop(self, video: VideoSource) -> None:
        for frame, captured_at in video.iter_frames(target_fps=self.target_fps):
            if self._shutdown_event.is_set():
                return

            spatial: list[SpatialDetection] = []
            fire = None
            try:
                spatial = yolo_detect(frame)
            except Exception as exc:
                logger.warning(f"[{self.name}] yolo error: {exc}")
            try:
                fire = self._fire.detect(frame)
            except Exception as exc:
                logger.warning(f"[{self.name}] fire error: {exc}")

            # Push annotated frame to the live-stream store BEFORE persistence,
            # so the UI feels snappy even if DB is slow.
            try:
                all_dets = list(spatial)
                if fire is not None and fire.confidence >= 0.4 and fire.bbox is not None:
                    all_dets.append(SpatialDetection(
                        threat_class="fire", confidence=fire.confidence, bbox=fire.bbox,
                    ))
                annotated = annotate(frame, all_dets)
                ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    put_frame(self.source_id, buf.tobytes())
            except Exception as exc:
                logger.warning(f"[{self.name}] annotate/encode error: {exc}")

            self._persist(captured_at, spatial, fire)

    def _persist(self, captured_at: datetime, spatial_list: list[SpatialDetection], fire) -> None:
        db = SessionLocal()
        try:
            src = db.query(Source).filter(Source.id == self.source_id).first()
            if not src:
                return

            new_alerts = []
            for sd in spatial_list:
                det = Detection(
                    source_id=self.source_id, detected_at=captured_at,
                    model_source=ModelSource.spatial, threat_class=sd.threat_class,
                    confidence=sd.confidence, spatial_score=sd.confidence,
                    bbox=sd.bbox, lat=src.location_lat, lon=src.location_lon,
                )
                db.add(det)
                db.flush()  # to get det.id

                if sd.confidence >= ALERT_THRESHOLD.get(sd.threat_class, 0.9):
                    new_alerts.append(self._build_alert(det, sd.threat_class, sd.confidence, src))

            if fire is not None and fire.confidence >= 0.4:
                det = Detection(
                    source_id=self.source_id, detected_at=captured_at,
                    model_source=ModelSource.spatial, threat_class="fire",
                    confidence=fire.confidence, spatial_score=fire.confidence,
                    bbox=fire.bbox, lat=src.location_lat, lon=src.location_lon,
                )
                db.add(det)
                db.flush()
                if fire.confidence >= ALERT_THRESHOLD["fire"]:
                    new_alerts.append(self._build_alert(det, "fire", fire.confidence, src))

            for a in new_alerts:
                db.add(a)

            src.last_frame_at = captured_at
            db.commit()
        except Exception as exc:
            logger.exception(f"[{self.name}] persist failed: {exc}")
            db.rollback()
        finally:
            db.close()

    def _build_alert(self, detection: Detection, threat_class: str, conf: float, source) -> Alert:
        if threat_class == "fire":
            sev = AlertSeverity.critical if conf >= 0.7 else AlertSeverity.high
            title = f"Possible fire detected at {source.name}"
        elif threat_class == "person" and conf >= 0.92:
            sev = AlertSeverity.low
            title = f"Person of interest at {source.name}"
        elif threat_class == "vehicle":
            sev = AlertSeverity.medium
            title = f"Vehicle activity at {source.name}"
        else:
            sev = AlertSeverity.low
            title = f"{threat_class.title()} detected at {source.name}"

        return Alert(
            detection_id=detection.id,
            source_id=source.id,
            severity=sev,
            status=AlertStatus.new,
            title=title,
            message=(
                f"{threat_class.title()} detected with {conf*100:.1f}% confidence "
                f"at {source.location_label or source.name}."
            ),
            lat=source.location_lat,
            lon=source.location_lon,
        )

    def _set_error(self, msg: str) -> None:
        db = SessionLocal()
        try:
            src = db.query(Source).filter(Source.id == self.source_id).first()
            if src:
                src.status = SourceStatus.error
                src.last_error = msg
                db.commit()
        finally:
            db.close()

    def _set_idle(self) -> None:
        db = SessionLocal()
        try:
            src = db.query(Source).filter(Source.id == self.source_id).first()
            if src:
                src.status = SourceStatus.idle
                db.commit()
        finally:
            db.close()


# Module-level worker registry
_workers: dict[str, IngestWorker] = {}
_workers_lock = threading.Lock()


def start_worker(source_id: str) -> bool:
    # Grab and evict any previous worker outside the lock so we can join()
    # without holding the lock for up to 6 seconds.
    with _workers_lock:
        existing = _workers.get(source_id)
        if existing and existing.is_alive():
            return False  # already streaming
        # Remove from registry before we release the lock.
        if existing is not None:
            existing.request_stop()
            _workers.pop(source_id, None)

    # Wait for the old thread to release the camera handle before opening a new one.
    # join() is safe here because _stop (the Thread-internal method) is no longer
    # shadowed — we renamed our event to _shutdown_event.
    if existing is not None:
        existing.join(timeout=6.0)

    w = IngestWorker(source_id)
    with _workers_lock:
        _workers[source_id] = w
    w.start()
    return True


def stop_worker(source_id: str) -> bool:
    with _workers_lock:
        w = _workers.get(source_id)
        if not w:
            return False
        w.request_stop()
        return True


def worker_status(source_id: str) -> str:
    w = _workers.get(source_id)
    if not w:
        return "stopped"
    return "running" if w.is_alive() else "stopped"


def all_workers_status() -> dict[str, str]:
    return {sid: worker_status(sid) for sid in list(_workers.keys())}
