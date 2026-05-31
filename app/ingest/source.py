"""VideoSource — source-agnostic video reader.

PATCHED:
  - Uses CAP_DSHOW backend for webcams on Windows -> opens in ~1s instead of
    10-60s with the default MSMF backend (fixes the "no signal for a minute").
  - Adds a small warm-up read after open so the first real frame is ready.
  - close() now releases robustly and tolerates being called twice.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional

import cv2
import numpy as np

from app.models import SourceKind


class SourceError(RuntimeError):
    pass


_IS_WINDOWS = sys.platform.startswith("win")


@dataclass
class VideoSource:
    kind: str
    locator: str
    _cap: Optional[cv2.VideoCapture] = None
    _native_fps: float = 30.0

    @classmethod
    def from_kind(cls, kind: str, locator: str) -> "VideoSource":
        if kind not in {k.value for k in SourceKind}:
            raise SourceError(f"Unknown source kind: {kind}")
        return cls(kind=kind, locator=locator)

    @classmethod
    def from_model(cls, source) -> "VideoSource":
        kind_value = source.kind.value if hasattr(source.kind, "value") else source.kind
        return cls(kind=kind_value, locator=source.locator)

    def open(self) -> None:
        if self._cap is not None and self._cap.isOpened():
            return
        if self.kind == "webcam":
            try:
                index = int(self.locator)
            except ValueError as exc:
                raise SourceError(f"Webcam locator must be integer: {self.locator}") from exc
            # On Windows, DirectShow opens far faster than the default MSMF backend.
            if _IS_WINDOWS:
                cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(index)
            else:
                cap = cv2.VideoCapture(index)
        else:
            cap = cv2.VideoCapture(self.locator)

        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            raise SourceError(f"Could not open {self.kind}: {self.locator}")

        self._cap = cap
        self._native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # Warm-up: discard the first couple of frames so the sensor stabilises.
        for _ in range(2):
            self._cap.read()

    def close(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def __enter__(self):
        self.open(); return self

    def __exit__(self, *_):
        self.close()

    def read_one(self) -> Optional[np.ndarray]:
        if self._cap is None:
            self.open()
        ok, frame = self._cap.read()
        return frame if ok else None

    def iter_frames(self, target_fps: int = 3, reconnect: bool = True) -> Iterator[tuple[np.ndarray, datetime]]:
        if self._cap is None:
            self.open()
        step = max(int(round(self._native_fps / max(target_fps, 1))), 1)
        idx = 0
        fail_count = 0
        while True:
            ok, frame = self._cap.read()
            if not ok:
                if self.kind == "file":
                    return
                if not reconnect:
                    raise SourceError(f"Lost frames from {self.kind}: {self.locator}")
                fail_count += 1
                if fail_count > 5:
                    raise SourceError(f"Repeated read failure from {self.kind}: {self.locator}")
                time.sleep(1.0)
                self.close()
                try:
                    self.open()
                except SourceError:
                    continue
                continue
            fail_count = 0
            if idx % step == 0:
                yield frame, datetime.now(timezone.utc)
            idx += 1

    def probe(self) -> dict:
        try:
            self.open()
            frame = self.read_one()
            width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if self._cap else None
            height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if self._cap else None
            return {
                "ok": frame is not None,
                "kind": self.kind,
                "locator": self.locator,
                "native_fps": round(self._native_fps, 2),
                "width": width,
                "height": height,
                "resolution": f"{width}x{height}" if width and height else None,
            }
        except SourceError as e:
            return {"ok": False, "kind": self.kind, "locator": self.locator, "error": str(e)}
        finally:
            self.close()
