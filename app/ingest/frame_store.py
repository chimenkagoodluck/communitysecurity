"""
In-memory shared latest-frame store.

The ingestion worker writes the most recent annotated frame for each source here.
The MJPEG streaming endpoint reads from it. This decouples the camera reader from
HTTP consumers, so we never compete for the webcam handle on Windows.

Design:
  - One slot per source_id, holding (jpeg_bytes, timestamp_seconds)
  - Threadsafe via a single lock (the dict is read/written from many threads)
  - Stale slot detection: if the worker dies, readers see "no recent frame"
    and serve a placeholder.
  - Two placeholder images: idle ("NO SIGNAL") and connecting ("INITIALISING…").
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np

_lock = threading.Lock()
_frames: dict[str, tuple[bytes, float]] = {}


def _build_placeholder(line1: str, line2: str, line1_color=(120, 150, 190)) -> bytes:
    h, w = 360, 640
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = (26, 36, 56)

    for x in range(0, w, 32):
        cv2.line(img, (x, 0), (x, h), (40, 50, 70), 1)
    for y in range(0, h, 32):
        cv2.line(img, (0, y), (w, y), (40, 50, 70), 1)

    (tw, _), _ = cv2.getTextSize(line1, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)
    cv2.putText(img, line1, (w // 2 - tw // 2, h // 2 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, line1_color, 2)
    (tw2, _), _ = cv2.getTextSize(line2, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.putText(img, line2, (w // 2 - tw2 // 2, h // 2 + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 115, 150), 1)

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


# Pre-rendered once at import time
_PLACEHOLDER_IDLE: bytes = _build_placeholder(
    "NO SIGNAL", "source is not being monitored"
)
_PLACEHOLDER_CONNECTING: bytes = _build_placeholder(
    "INITIALISING CAMERA", "live feed will appear shortly…",
    line1_color=(80, 180, 255),
)


def put_frame(source_id: str, jpeg_bytes: bytes) -> None:
    """Worker calls this with each fresh annotated frame."""
    with _lock:
        _frames[source_id] = (jpeg_bytes, time.time())


def get_frame(source_id: str, max_age_seconds: float = 3.0,
              worker_running: bool = False) -> bytes:
   
    with _lock:
        entry = _frames.get(source_id)
    if entry is None:
        return _PLACEHOLDER_CONNECTING if worker_running else _PLACEHOLDER_IDLE
    jpeg, ts = entry
    if time.time() - ts > max_age_seconds:
        return _PLACEHOLDER_CONNECTING if worker_running else _PLACEHOLDER_IDLE
    return jpeg


def clear_frame(source_id: str) -> None:
    """Called when ingestion stops."""
    with _lock:
        _frames.pop(source_id, None)


def has_recent_frame(source_id: str, max_age_seconds: float = 3.0) -> bool:
    with _lock:
        entry = _frames.get(source_id)
    if not entry:
        return False
    return (time.time() - entry[1]) <= max_age_seconds
