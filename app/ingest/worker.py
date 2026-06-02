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
import time
from datetime import datetime, timezone
from typing import Optional

import cv2
from loguru import logger

from app.config import settings
from app.db import SessionLocal
from app.ingest.frame_store import clear_frame, put_frame
from app.ingest.source import SourceError, VideoSource
from app.ml.detect import analyze_frame
from app.ml.fire import FireDetector
from app.ml.weapon_gate import WeaponGate
from app.models import (
    Alert, AlertSeverity, AlertStatus, Detection, ModelSource, Source, SourceStatus,
)

# A harmful detection must clear this confidence floor before it raises an alert.
HARMFUL_ALERT_FLOOR = 0.40

# Per-alert-key cooldown so a weapon held in view doesn't flood the alerts table
# (the worker runs at a few fps, so without this it would create alerts every frame).
ALERT_COOLDOWN_SECONDS = 15.0

PERSON_CLASSES = {"person", "armed-person"}


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
        self._weapon_gate = WeaponGate()  # temporal persistence -> suppresses flickering weapon FPs
        self._last_alert_at: dict[str, float] = {}  # alert-key -> monotonic time

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

            # Single unified detection pass (YOLO + weapon model + fire +
            # armed-person escalation), shared with image/video upload.
            try:
                annotated, detections = analyze_frame(
                    frame, fire_detector=self._fire, weapon_gate=self._weapon_gate)
            except Exception as exc:
                logger.warning(f"[{self.name}] analyze error: {exc}")
                annotated, detections = frame, []

            # Push annotated frame to the live-stream store BEFORE persistence,
            # so the UI feels snappy even if DB is slow.
            try:
                ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    put_frame(self.source_id, buf.tobytes())
            except Exception as exc:
                logger.warning(f"[{self.name}] encode error: {exc}")

            self._persist(captured_at, detections)

    def _persist(self, captured_at: datetime, detections: list[dict]) -> None:
        db = SessionLocal()
        try:
            src = db.query(Source).filter(Source.id == self.source_id).first()
            if not src:
                return

            now_mono = time.monotonic()
            persons: list[dict] = []
            for d in detections:
                det = Detection(
                    source_id=self.source_id, detected_at=captured_at,
                    model_source=ModelSource.spatial, threat_class=d["class"],
                    confidence=d["confidence"], spatial_score=d["confidence"],
                    bbox=d["bbox"], lat=src.location_lat, lon=src.location_lon,
                )
                db.add(det)
                db.flush()  # to get det.id

                if d["class"] in PERSON_CLASSES:
                    persons.append(d)

                if d["harmful"] and d["confidence"] >= HARMFUL_ALERT_FLOOR \
                        and self._cooldown_ok(d["class"], now_mono):
                    db.add(self._build_alert(det, d, src))

            # Crowd proxy: several people clustered together -> disturbance alert.
            if self._person_cluster(persons) >= settings.CROWD_MIN_PERSONS \
                    and self._cooldown_ok("crowd", now_mono):
                db.add(self._build_crowd_alert(persons, src))

            src.last_frame_at = captured_at
            db.commit()
        except Exception as exc:
            logger.exception(f"[{self.name}] persist failed: {exc}")
            db.rollback()
        finally:
            db.close()

    def _cooldown_ok(self, key: str, now_mono: float) -> bool:
        """True if enough time has passed since the last alert with this key."""
        if now_mono - self._last_alert_at.get(key, 0.0) >= ALERT_COOLDOWN_SECONDS:
            self._last_alert_at[key] = now_mono
            return True
        return False

    @staticmethod
    def _person_cluster(persons: list[dict]) -> int:
        """Size of the densest group of people whose box-centres are close together."""
        centers = [(p["bbox"]["x"] + p["bbox"]["w"] / 2, p["bbox"]["y"] + p["bbox"]["h"] / 2)
                   for p in persons if p.get("bbox")]
        if len(centers) < settings.CROWD_MIN_PERSONS:
            return len(centers)
        d2 = settings.CROWD_PROXIMITY_DIST ** 2
        best = 0
        for cx, cy in centers:
            n = sum(1 for ox, oy in centers if (cx - ox) ** 2 + (cy - oy) ** 2 <= d2)
            best = max(best, n)
        return best

    def _build_alert(self, detection: Detection, d: dict, source) -> Alert:
        cls, conf = d["class"], d["confidence"]
        sev = AlertSeverity(d["severity"])  # severity strings match the enum values
        if cls == "fire":
            title = f"Possible fire detected at {source.name}"
        elif cls == "armed-person":
            title = f"Armed person detected at {source.name}"
        elif cls in ("gun", "knife", "weapon"):
            title = f"Weapon ({cls}) detected at {source.name}"
        else:
            title = f"{cls.title()} detected at {source.name}"

        return Alert(
            detection_id=detection.id,
            source_id=source.id,
            severity=sev,
            status=AlertStatus.new,
            title=title,
            message=(
                f"{cls.replace('-', ' ').title()} detected with {conf * 100:.1f}% confidence "
                f"at {source.location_label or source.name}."
            ),
            lat=source.location_lat,
            lon=source.location_lon,
        )

    def _build_crowd_alert(self, persons: list[dict], source) -> Alert:
        n = len(persons)
        armed = any(p["class"] == "armed-person" for p in persons)
        sev = AlertSeverity.high if armed else AlertSeverity.medium
        return Alert(
            source_id=source.id,
            severity=sev,
            status=AlertStatus.new,
            title=f"Crowd / disturbance at {source.name}",
            message=(
                f"{n} people detected in proximity"
                f"{' — armed person present' if armed else ''} "
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
