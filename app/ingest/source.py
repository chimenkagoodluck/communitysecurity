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
from loguru import logger

from app.models import SourceKind

# How many device indices to scan when the configured webcam index is unavailable.
_WEBCAM_SCAN_RANGE = 6


class SourceError(RuntimeError):
    pass


_IS_WINDOWS = sys.platform.startswith("win")


def normalize_locator(locator: str) -> str:
    """Clean a user-supplied locator.

    Windows Explorer's "Copy as path" wraps the path in double quotes, and users
    sometimes paste those quotes in. OpenCV then treats the quotes as part of the
    filename and silently fails to open. Strip surrounding whitespace and a single
    matching pair of wrapping quotes.
    """
    s = (locator or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


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

    @staticmethod
    def _safe_to_scan() -> bool:
        """True if at most one ingest worker is alive (i.e. only the caller).

        Probing webcam indices means briefly opening captures; doing that while
        *another* worker streams a device can hard-crash the interpreter on Windows
        (the single-handle rule). The worker calling open() is itself counted as one
        live worker, so we allow the scan only when the live-worker count is <= 1.
        With other workers running we skip the scan and let the configured index
        fail loudly instead.
        """
        try:
            from app.ingest.worker import _workers, _workers_lock
        except Exception:
            return True
        with _workers_lock:
            return sum(1 for w in _workers.values() if w.is_alive()) <= 1

    @staticmethod
    def _open_webcam_index(index: int) -> Optional[cv2.VideoCapture]:
        """Try to open one webcam index. Returns an opened capture or None."""
        # On Windows, DirectShow opens far faster than the default MSMF backend.
        if _IS_WINDOWS:
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(index)
        else:
            cap = cv2.VideoCapture(index)
        if cap.isOpened():
            return cap
        cap.release()
        return None

    def open(self) -> None:
        if self._cap is not None and self._cap.isOpened():
            return
        # Defensive: strip wrapping quotes/whitespace so a path pasted via
        # "Copy as path" (which adds quotes) still opens.
        self.locator = normalize_locator(self.locator)
        if self.kind == "webcam":
            try:
                index = int(self.locator)
            except ValueError as exc:
                raise SourceError(f"Webcam locator must be integer: {self.locator}") from exc

            cap = self._open_webcam_index(index)
            if cap is None and self._safe_to_scan():
                # The configured index isn't present on this machine (common when a
                # source was created on a different laptop). Fall back to the first
                # camera that actually opens so "the system has a camera" just works.
                # Guarded by _safe_to_scan() so we never probe a device another live
                # worker may hold (the single-handle rule — see CLAUDE.md).
                for alt in range(_WEBCAM_SCAN_RANGE):
                    if alt == index:
                        continue
                    cap = self._open_webcam_index(alt)
                    if cap is not None:
                        logger.warning(
                            f"webcam index {index} unavailable; using detected camera at index {alt}"
                        )
                        self.locator = str(alt)
                        break
            if cap is None:
                raise SourceError(
                    f"Could not open webcam: {index} - no camera found at that index "
                    f"or at any index 0-{_WEBCAM_SCAN_RANGE - 1}. Is a camera connected "
                    f"and not in use by another app?"
                )
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
