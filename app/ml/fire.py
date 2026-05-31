"""Fire / flame detection via HSV color + motion heuristic."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Optional

import cv2
import numpy as np

_LOWER_1 = np.array([0,   120, 180], dtype=np.uint8)
_UPPER_1 = np.array([25,  255, 255], dtype=np.uint8)
_LOWER_2 = np.array([160, 120, 180], dtype=np.uint8)
_UPPER_2 = np.array([180, 255, 255], dtype=np.uint8)


@dataclass
class FireDetection:
    confidence: float
    bbox: Optional[dict] = None


class FireDetector:
    def __init__(self, history: int = 8, min_area_ratio: float = 0.005):
        self._masks: deque[np.ndarray] = deque(maxlen=history)
        self._lock = Lock()
        self._min_area_ratio = min_area_ratio

    def detect(self, frame: np.ndarray) -> FireDetection:
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.bitwise_or(cv2.inRange(hsv, _LOWER_1, _UPPER_1),
                              cv2.inRange(hsv, _LOWER_2, _UPPER_2))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        area_ratio = float(mask.sum()) / (255.0 * h * w)

        with self._lock:
            self._masks.append(mask)
            flicker = self._flicker_score()

        color_score = min(area_ratio / 0.10, 1.0)
        flicker_score = min(flicker / 0.20, 1.0)
        confidence = 0.6 * color_score + 0.4 * flicker_score

        if area_ratio < self._min_area_ratio:
            return FireDetection(confidence=0.0, bbox=None)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        bbox = None
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, bw, bh = cv2.boundingRect(largest)
            bbox = {"x": round(x/w,4), "y": round(y/h,4),
                    "w": round(bw/w,4), "h": round(bh/h,4)}
        return FireDetection(confidence=round(confidence, 4), bbox=bbox)

    def _flicker_score(self) -> float:
        if len(self._masks) < 2:
            return 0.0
        masks = list(self._masks)
        diffs = []
        for prev, curr in zip(masks[:-1], masks[1:]):
            diffs.append(float(cv2.absdiff(prev, curr).sum()) / (255.0 * prev.size))
        return float(np.mean(diffs)) if diffs else 0.0
