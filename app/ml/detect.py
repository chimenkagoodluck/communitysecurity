"""
Unified per-frame analysis — the single detection entry point for the whole app.

    analyze_frame(frame) -> (annotated_frame, detections)

where each detection is a plain dict:
    {
      "class":      str,                       # e.g. "person", "knife", "fire"
      "confidence": float,                     # 0..1
      "bbox":       {"x","y","w","h"},         # normalised 0..1
      "harmful":    bool,                      # threat-bearing class?
      "severity":   "low"|"medium"|"high"|"critical",
    }

This is reused by the image-upload endpoint, the video-upload endpoint, and
(BLOCK 5) the live ingestion worker, so detection logic lives in exactly one place.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from app.config import settings
from app.ml import weapon as weapon_model
from app.ml.fire import FireDetector
from app.ml.weapon_gate import WeaponGate
from app.ml.yolo import detect as yolo_detect

# Classes treated as harmful / threat-bearing. The dedicated weapon model
# (BLOCK 2) adds gun/pistol/rifle/weapon; "knife" already comes from COCO.
HARMFUL_CLASSES = {"gun", "pistol", "rifle", "weapon", "knife", "machete", "fire"}

# Weapon classes used by the person+weapon escalation rule.
WEAPON_CLASSES = {"gun", "pistol", "rifle", "weapon", "knife", "machete"}
_FIREARM_CLASSES = {"gun", "pistol", "rifle", "weapon"}

# Box colour by severity (BGR). Harmful detections stand out in red/orange.
_SEV_COLOR = {
    "critical": (60, 60, 240),    # red
    "high":     (60, 130, 245),   # orange
    "medium":   (60, 200, 245),   # amber
    "low":      (190, 190, 190),  # grey
}

# Default fire detector for callers that don't keep their own state
# (single-image analysis). The live worker passes its own instance so the
# temporal flicker score accumulates across the stream.
_default_fire = FireDetector()


def severity_for(threat_class: str, confidence: float) -> str:
    """Map a class + confidence to a severity bucket."""
    if threat_class in {"gun", "pistol", "rifle", "weapon"}:
        return "critical" if confidence >= 0.55 else "high"
    if threat_class in {"knife", "machete"}:
        return "high" if confidence >= 0.50 else "medium"
    if threat_class == "fire":
        return "critical" if confidence >= 0.70 else "high"
    # person / vehicle / bicycle / motorcycle are informational on their own.
    return "low"


def analyze_frame(
    frame: np.ndarray,
    fire_detector: Optional[FireDetector] = None,
    weapon_gate: Optional[WeaponGate] = None,
) -> tuple[np.ndarray, list[dict]]:
    """Run all detectors on one BGR frame and return (annotated_frame, detections).

    `weapon_gate`, when supplied (video upload / live worker), suppresses weapon
    detections that don't persist across recent frames — killing the flickering
    false positives the weapon model produces on drone footage. Single-image
    callers pass None (no temporal context); they still get the threshold and
    person-overlap filters below.
    """
    detections: list[dict] = []

    # 1. Spatial detection (YOLO): person / vehicle / knife / ...
    try:
        for sd in yolo_detect(frame):
            detections.append({
                "class": sd.threat_class,
                "confidence": round(sd.confidence, 4),
                "bbox": sd.bbox,
                "harmful": sd.threat_class in HARMFUL_CLASSES,
                "severity": severity_for(sd.threat_class, sd.confidence),
            })
    except Exception:
        pass

    # 2. Dedicated weapon model (gun/knife) — runs alongside COCO. No-op if the
    #    weapon .pt isn't installed; COCO 'knife' above still provides a weapon class.
    try:
        for wd in weapon_model.detect(frame):
            detections.append({
                "class": wd.threat_class,
                "confidence": round(wd.confidence, 4),
                "bbox": wd.bbox,
                "harmful": True,
                "severity": severity_for(wd.threat_class, wd.confidence),
            })
    except Exception:
        pass

    # 3. Fire detection (HSV colour + temporal flicker heuristic)
    fd = fire_detector or _default_fire
    try:
        fire = fd.detect(frame)
        if fire.confidence >= 0.4 and fire.bbox is not None:
            detections.append({
                "class": "fire",
                "confidence": round(fire.confidence, 4),
                "bbox": fire.bbox,
                "harmful": True,
                "severity": severity_for("fire", fire.confidence),
            })
    except Exception:
        pass

    # 4. Suppress weapon false positives (covers COCO 'knife' and the weapon model):
    #    (B) drop weapons that don't overlap a person, then
    #    (C) drop weapons that don't persist across the recent frame window.
    detections = _filter_weapons(detections, weapon_gate)

    # 5. Merge overlapping duplicates (e.g. COCO knife + weapon-model knife),
    #    then escalate any person holding a weapon to "armed-person".
    detections = _dedupe(detections)
    detections = _escalate_armed_persons(detections)

    return annotate(frame, detections), detections


def _overlaps_any_person(weapon_bbox: dict, persons: list[dict]) -> bool:
    """True if a weapon box meaningfully overlaps any person box."""
    return any(
        _center_inside(weapon_bbox, p["bbox"]) or _iou(weapon_bbox, p["bbox"]) > 0.02
        for p in persons if p.get("bbox")
    )


def _filter_weapons(dets: list[dict], gate: Optional[WeaponGate]) -> list[dict]:
    """Apply the person-overlap (B) and temporal-persistence (C) gates to weapons."""
    persons = [d for d in dets if d["class"] == "person" and d.get("bbox")]
    weapons = [d for d in dets if d["class"] in WEAPON_CLASSES]
    others = [d for d in dets if d["class"] not in WEAPON_CLASSES]

    # (B) a weapon with no person around it is a hallucination (e.g. on pavement).
    if settings.WEAPON_REQUIRE_PERSON:
        weapons = [w for w in weapons
                   if w.get("bbox") and _overlaps_any_person(w["bbox"], persons)]

    # (C) require temporal persistence. Always call the gate (even with an empty
    #     list) so its sliding window keeps advancing and gaps count as misses.
    if gate is not None:
        weapons = gate.confirm(weapons)

    return others + weapons


# ── Box geometry helpers (operate on normalised {x,y,w,h} boxes) ──────────────

def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _center_inside(inner: dict, outer: dict) -> bool:
    cx, cy = inner["x"] + inner["w"] / 2, inner["y"] + inner["h"] / 2
    return (outer["x"] <= cx <= outer["x"] + outer["w"]
            and outer["y"] <= cy <= outer["y"] + outer["h"])


def _dedupe(dets: list[dict]) -> list[dict]:
    """Drop near-duplicate boxes of the same class, keeping the highest confidence."""
    out: list[dict] = []
    for d in sorted(dets, key=lambda x: x["confidence"], reverse=True):
        if any(k["class"] == d["class"] and d.get("bbox") and k.get("bbox")
               and _iou(k["bbox"], d["bbox"]) > 0.55 for k in out):
            continue
        out.append(d)
    return out


def _escalate_armed_persons(dets: list[dict]) -> list[dict]:
    """A person overlapping a weapon becomes an 'armed-person' (high/critical)."""
    weapons = [d for d in dets if d["class"] in WEAPON_CLASSES and d.get("bbox")]
    if not weapons:
        return dets
    for d in dets:
        if d["class"] != "person" or not d.get("bbox"):
            continue
        near = [w for w in weapons
                if _center_inside(w["bbox"], d["bbox"]) or _iou(w["bbox"], d["bbox"]) > 0.02]
        if not near:
            continue
        d["class"] = "armed-person"
        d["harmful"] = True
        d["severity"] = "critical" if any(w["class"] in _FIREARM_CLASSES for w in near) else "high"
    return dets


def annotate(frame: np.ndarray, detections: list[dict]) -> np.ndarray:
    """Draw severity-coloured boxes + labels onto a copy of the frame."""
    img = frame.copy()
    h, w = img.shape[:2]
    for d in detections:
        bb = d.get("bbox")
        if not bb:
            continue
        x = int(bb["x"] * w)
        y = int(bb["y"] * h)
        bw = int(bb["w"] * w)
        bh = int(bb["h"] * h)
        color = _SEV_COLOR.get(d["severity"], (190, 190, 190))
        thickness = 3 if d.get("harmful") else 2
        cv2.rectangle(img, (x, y), (x + bw, y + bh), color, thickness)

        # cv2's Hershey font can't render emoji, so flag harmful boxes with "! ".
        prefix = "! " if d.get("harmful") else ""
        label = f"{prefix}{d['class']} {int(d['confidence'] * 100)}%"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(img, (x, y - th - 8), (x + tw + 6, y), color, -1)
        cv2.putText(img, label, (x + 3, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (15, 20, 35), 1, cv2.LINE_AA)
    return img
