from __future__ import annotations

from threading import Lock

import numpy as np
from loguru import logger

from app.config import PROJECT_ROOT, settings
from app.ml.yolo import SpatialDetection

_lock = Lock()
_model = None            # the loaded YOLO model, or None
_load_attempted = False  # so we only log "missing" once


def _canonical_class(name: str) -> str | None:
    """Map a model's own class name to our canonical weapon class, or None to skip."""
    n = str(name).strip().lower()
    if any(k in n for k in ("pistol", "handgun", "hand gun", "revolver", "firearm",
                            "rifle", "shotgun", "gun")):
        return "gun"
   
    if any(k in n for k in ("machete", "matchet", "celurit", "clurit", "panga",
                            "parang", "golok", "cutlass")):
        return "machete"
    if any(k in n for k in ("knife", "blade", "dagger", "sword")):
        return "knife"
    if any(k in n for k in ("weapon", "grenade", "explos", "bomb")):
        return "weapon"
    return None  


def get_model():
   
    global _model, _load_attempted
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        if _load_attempted:
            return None
        _load_attempted = True
        path = PROJECT_ROOT / settings.WEAPON_MODEL_PATH
        if not path.exists():
            logger.warning(
                f"Weapon model not found at {path} — weapon detection DISABLED. "
                f"Falling back to COCO knife + person. "
                f"Drop a YOLOv8 weapon .pt there to enable gun detection."
            )
            return None
        try:
            from ultralytics import YOLO
            _model = YOLO(str(path))
            names = list(_model.names.values()) if hasattr(_model, "names") else []
            mapped = sorted({c for c in (_canonical_class(n) for n in names) if c})
            logger.info(f"Weapon model loaded from {path.name} | "
                        f"raw classes={names} -> canonical={mapped}")
        except Exception as exc:
            logger.error(f"Failed to load weapon model {path}: {exc}")
            _model = None
        return _model


def available() -> bool:
    return get_model() is not None


def detect(
    frame: np.ndarray,
    conf: float | None = None,
    imgsz: int | None = None,
    augment: bool = False,
) -> list[SpatialDetection]:
    
    model = get_model()
    if model is None:
        return []
    conf = settings.WEAPON_CONFIDENCE_THRESHOLD if conf is None else conf
    kwargs = {"conf": conf, "verbose": False, "augment": augment}
    if imgsz is not None:
        kwargs["imgsz"] = imgsz
    results = model.predict(frame, **kwargs)
    if not results:
        return []
    res = results[0]
    if res.boxes is None:
        return []
    h, w = frame.shape[:2]
    names = model.names
    out: list[SpatialDetection] = []
    for box in res.boxes:
        cls_id = int(box.cls.item())
        raw_name = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)
        canon = _canonical_class(raw_name)
        if canon is None:
            continue
        conf = float(box.conf.item())
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
        out.append(SpatialDetection(
            threat_class=canon,
            confidence=conf,
            bbox={"x": round(x1 / w, 4), "y": round(y1 / h, 4),
                  "w": round((x2 - x1) / w, 4), "h": round((y2 - y1) / h, 4)},
        ))
    return out
