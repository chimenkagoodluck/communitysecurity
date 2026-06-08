from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

import cv2
import numpy as np

from app.config import settings

_yolo_lock = Lock()
_yolo_singleton = None

TARGET_CLASSES = {
    0: "person",
    1: "bicycle",
    2: "vehicle",
    3: "motorcycle",
    5: "vehicle",   # bus
    7: "vehicle",   # truck
    43: "knife",    # COCO 'knife' — a harmful class even before the dedicated weapon model (BLOCK 2)
}

# Color per class (BGR) for drawing
DRAW_COLORS = {
    "person":     (248, 189,  56),   # cyan/blue in BGR -> sky
    "vehicle":    (128, 222,  74),   # green
    "fire":       ( 71, 113, 248),   # red
    "bicycle":    ( 36, 191, 251),   # amber
    "motorcycle": ( 36, 191, 251),   # amber
    "fight":      ( 71,  71, 248),   # bright red
    "violence":   ( 71,  71, 248),
}


@dataclass
class SpatialDetection:
    threat_class: str
    confidence: float
    bbox: dict  # normalised


def get_model():
    global _yolo_singleton
    if _yolo_singleton is not None:
        return _yolo_singleton
    with _yolo_lock:
        if _yolo_singleton is None:
            from ultralytics import YOLO
            _yolo_singleton = YOLO("yolov8n.pt")
    return _yolo_singleton


def detect(frame: np.ndarray, imgsz: int | None = None) -> list[SpatialDetection]:
    model = get_model()
    kwargs = {"conf": settings.SPATIAL_CONFIDENCE_THRESHOLD, "verbose": False}
    if imgsz is not None:
        kwargs["imgsz"] = imgsz
    results = model.predict(frame, **kwargs)
    h, w = frame.shape[:2]
    out: list[SpatialDetection] = []
    if not results:
        return out
    res = results[0]
    if res.boxes is None:
        return out
    for box in res.boxes:
        cls_id = int(box.cls.item())
        if cls_id not in TARGET_CLASSES:
            continue
        conf = float(box.conf.item())
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
        out.append(SpatialDetection(
            threat_class=TARGET_CLASSES[cls_id],
            confidence=conf,
            bbox={"x": round(x1 / w, 4), "y": round(y1 / h, 4),
                  "w": round((x2 - x1) / w, 4), "h": round((y2 - y1) / h, 4)},
        ))
    return out


def annotate(frame: np.ndarray, detections: list[SpatialDetection]) -> np.ndarray:
    """Draw bboxes + labels onto a frame copy. Used by the live MJPEG stream."""
    img = frame.copy()
    h, w = img.shape[:2]
    for d in detections:
        x = int(d.bbox["x"] * w)
        y = int(d.bbox["y"] * h)
        bw = int(d.bbox["w"] * w)
        bh = int(d.bbox["h"] * h)
        color = DRAW_COLORS.get(d.threat_class, (255, 255, 255))
        cv2.rectangle(img, (x, y), (x + bw, y + bh), color, 2)
        label = f"{d.threat_class} {int(d.confidence * 100)}%"
        # Label background
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(img, (x, y - th - 8), (x + tw + 6, y), color, -1)
        cv2.putText(img, label, (x + 3, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (15, 20, 35), 1, cv2.LINE_AA)
    return img
