from __future__ import annotations

from collections import deque
from typing import Optional

from app.config import settings


class WeaponGate:
    def __init__(
        self,
        window: Optional[int] = None,
        min_hits: Optional[int] = None,
        match_dist: Optional[float] = None,
    ):
        self.window = max(1, window if window is not None else settings.WEAPON_PERSIST_WINDOW)
        self.min_hits = max(1, min_hits if min_hits is not None else settings.WEAPON_PERSIST_MIN)
        self.match_dist = match_dist if match_dist is not None else settings.WEAPON_MATCH_DIST
        self._d2 = self.match_dist ** 2
        # Each history item is a list of (class, cx, cy) for that frame.
        self._history: deque[list[tuple[str, float, float]]] = deque(maxlen=self.window)

    @staticmethod
    def _center(bbox: dict) -> tuple[float, float]:
        return bbox["x"] + bbox["w"] / 2, bbox["y"] + bbox["h"] / 2

    def confirm(self, weapon_dets: list[dict]) -> list[dict]:
        
        current: list[tuple[str, float, float]] = []
        for d in weapon_dets:
            bb = d.get("bbox")
            if not bb:
                continue
            cx, cy = self._center(bb)
            current.append((d["class"], cx, cy))

        # Count over the recent window INCLUDING the current frame.
        frames = list(self._history) + [current]

        confirmed: list[dict] = []
        for d in weapon_dets:
            bb = d.get("bbox")
            if not bb:
                continue
            cx, cy = self._center(bb)
            hits = sum(
                1 for fr in frames
                if any(c == d["class"] and (cx - x) ** 2 + (cy - y) ** 2 <= self._d2
                       for (c, x, y) in fr)
            )
            if hits >= self.min_hits:
                confirmed.append(d)

        self._history.append(current)
        return confirmed
