"""FaceLandmarker wrapper that detects eye open/closed from IRIS VISIBILITY.

This does NOT measure eyelid shape at all. It locates each iris from the iris
landmarks, then looks at the image pixels where the iris should be:

    - When the eye is OPEN the iris/pupil is visible: the center is dark and the
      local region has high contrast (dark iris + pupil + bright sclera).
    - When the eye is CLOSED the eyelid skin covers the iris: the region is
      smooth and skin-toned (bright, low contrast).

So openness = darkness(iris center vs surround) + local contrast. A higher value
means "the iris is there" (open); a low value means "no iris" (closed).
Calibration maps these per-eye values to a threshold.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "mediapipe is required. Install dependencies with:\n"
        "    pip install -r requirements.txt"
    ) from exc

import config

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)   # RGB -> gray


@dataclass
class EyeReading:
    """One frame's worth of eye measurements (iris visibility)."""

    found: bool = False
    open_left: float = 0.0          # smoothed iris-visibility, anatomical left eye
    open_right: float = 0.0         # smoothed iris-visibility, anatomical right eye
    open_avg: float = 0.0
    open_left_raw: float = 0.0
    open_right_raw: float = 0.0
    # Pixel coordinates for drawing eye outlines in the HUD (visualization only).
    left_ring: List[Tuple[int, int]] = field(default_factory=list)
    right_ring: List[Tuple[int, int]] = field(default_factory=list)
    # Iris circles (cx, cy, radius) in pixels, for drawing.
    iris_left: Tuple[int, int, int] | None = None
    iris_right: Tuple[int, int, int] | None = None


def _iris_center_radius(pts5: np.ndarray) -> tuple[np.ndarray, float]:
    """Iris center and radius (pixels) from 5 points (center first)."""
    center = pts5[0]
    ring = pts5[1:]
    radius = float(np.mean(np.linalg.norm(ring - center, axis=1)))
    return center, radius


def _ring_pixels(gray: np.ndarray, cx: float, cy: float,
                 r_in: float, r_out: float) -> np.ndarray:
    """Grayscale pixels in the annulus r_in..r_out around (cx, cy)."""
    h, w = gray.shape
    ro = max(1, int(np.ceil(r_out)))
    x0, x1 = max(0, int(cx) - ro), min(w, int(cx) + ro + 1)
    y0, y1 = max(0, int(cy) - ro), min(h, int(cy) + ro + 1)
    if x1 <= x0 or y1 <= y0:
        return np.empty(0, dtype=np.float32)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    d2 = (xs - cx) ** 2 + (ys - cy) ** 2
    m = (d2 >= r_in * r_in) & (d2 <= r_out * r_out)
    return gray[y0:y1, x0:x1][m]


def _iris_visibility(gray: np.ndarray, cx: float, cy: float, rad: float) -> float:
    """How clearly the iris is visible at (cx, cy). High == open, low == closed.

    Combines (a) how much darker the iris/pupil center is than the surrounding
    ring, and (b) the local contrast in the iris disk. Both are near zero over
    smooth eyelid skin (a closed eye) and large over a visible iris.
    """
    center = _ring_pixels(gray, cx, cy, 0.0, max(2.0, 0.6 * rad))
    surround = _ring_pixels(gray, cx, cy, 1.5 * rad, 2.8 * rad)
    disk = _ring_pixels(gray, cx, cy, 0.0, max(2.0, 1.0 * rad))
    if center.size == 0 or surround.size == 0 or disk.size == 0:
        return 0.0
    darkness = max(0.0, float(np.median(surround) - center.mean())) / 255.0
    contrast = float(disk.std()) / 255.0
    return darkness + contrast


class EyeTracker:
    """FaceLandmarker-based iris-visibility blink detector."""

    def __init__(self) -> None:
        if not config.MODEL_PATH.exists():
            raise SystemExit(
                f"Model not found at {config.MODEL_PATH}.\n"
                "Download it with:  python download_model.py"
            )
        base = mp_python.BaseOptions(model_asset_path=str(config.MODEL_PATH))
        options = vision.FaceLandmarkerOptions(
            base_options=base,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._left_hist: deque[float] = deque(maxlen=config.SMOOTH_WINDOW)
        self._right_hist: deque[float] = deque(maxlen=config.SMOOTH_WINDOW)
        self._last_ts = -1

    @staticmethod
    def _median(hist: deque[float]) -> float:
        return float(np.median(hist)) if hist else 0.0

    def process(self, frame_rgb: np.ndarray, timestamp_ms: float) -> EyeReading:
        """Run FaceLandmarker and return smoothed per-eye iris visibility.

        ``timestamp_ms`` must be monotonically increasing (VIDEO running mode).
        """
        h, w = frame_rgb.shape[:2]

        ts = int(timestamp_ms)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                            data=np.ascontiguousarray(frame_rgb))
        result = self._landmarker.detect_for_video(mp_image, ts)

        if not result.face_landmarks:
            return EyeReading(found=False)

        lm = result.face_landmarks[0]
        if len(lm) < 478:
            raise SystemExit(
                "FaceLandmarker did not return iris landmarks (need 478 points). "
                "Re-download the model with:  python download_model.py"
            )

        gray = frame_rgb.astype(np.float32) @ _LUMA

        def pts_for(indices) -> np.ndarray:
            return np.array([[lm[i].x * w, lm[i].y * h] for i in indices],
                            dtype=np.float32)

        cA, rA = _iris_center_radius(pts_for(config.IRIS_GROUP_A))
        cB, rB = _iris_center_radius(pts_for(config.IRIS_GROUP_B))

        # Assign iris groups to eyes by horizontal position (iris-only, no
        # eyelid landmarks). In a mirrored (selfie) frame the anatomical LEFT
        # eye appears on the image's right (larger x).
        if (cA[0] > cB[0]) == config.FLIP_HORIZONTAL:
            (lc, lr), (rc, rr) = (cA, rA), (cB, rB)
        else:
            (lc, lr), (rc, rr) = (cB, rB), (cA, rA)

        raw_left = _iris_visibility(gray, lc[0], lc[1], lr)
        raw_right = _iris_visibility(gray, rc[0], rc[1], rr)

        self._left_hist.append(raw_left)
        self._right_hist.append(raw_right)
        sm_left = self._median(self._left_hist)
        sm_right = self._median(self._right_hist)

        left_ring = [(int(lm[i].x * w), int(lm[i].y * h))
                     for i in config.LEFT_EYE_RING]
        right_ring = [(int(lm[i].x * w), int(lm[i].y * h))
                      for i in config.RIGHT_EYE_RING]

        return EyeReading(
            found=True,
            open_left=sm_left,
            open_right=sm_right,
            open_avg=(sm_left + sm_right) / 2.0,
            open_left_raw=raw_left,
            open_right_raw=raw_right,
            left_ring=left_ring,
            right_ring=right_ring,
            iris_left=(int(lc[0]), int(lc[1]), int(round(lr))),
            iris_right=(int(rc[0]), int(rc[1]), int(round(rr))),
        )

    def close(self) -> None:
        self._landmarker.close()
