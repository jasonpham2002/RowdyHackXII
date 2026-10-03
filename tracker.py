"""FaceLandmarker wrapper that turns a camera frame into per-eye openness (EAR).

Uses the MediaPipe Tasks ``FaceLandmarker`` (the modern replacement for the old
``solutions.face_mesh`` API) to locate eyelid landmarks, computes the Eye Aspect
Ratio for each eye, and smooths it with a short rolling median so single-frame
landmark jitter does not create phantom blinks.
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


@dataclass
class EyeReading:
    """One frame's worth of eye measurements.

    The ``ear_*`` fields carry the ACTIVE openness metric (iris-normalized when
    available, otherwise classic EAR). ``metric`` says which one.
    """

    found: bool = False
    ear_left: float = 0.0           # smoothed openness, anatomical left eye
    ear_right: float = 0.0          # smoothed openness, anatomical right eye
    ear_avg: float = 0.0
    ear_left_raw: float = 0.0
    ear_right_raw: float = 0.0
    metric: str = "ear"
    # Pixel coordinates for drawing eye outlines in the HUD.
    left_ring: List[Tuple[int, int]] = field(default_factory=list)
    right_ring: List[Tuple[int, int]] = field(default_factory=list)
    # Iris circles (cx, cy, radius) in pixels, for drawing (None if no iris).
    iris_left: Tuple[int, int, int] | None = None
    iris_right: Tuple[int, int, int] | None = None


def _ear_from_points(pts: np.ndarray) -> float:
    """Eye Aspect Ratio from the 6 ordered landmark points.

    pts order: p1, p2, p3, p4, p5, p6 (see config for the index mapping).
    """
    p1, p2, p3, p4, p5, p6 = pts
    vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    horizontal = 2.0 * np.linalg.norm(p1 - p4)
    if horizontal <= 1e-6:
        return 0.0
    return float(vertical / horizontal)


def _lid_gap(pts: np.ndarray) -> float:
    """Average vertical eyelid distance (pixels) from the 6 EAR points."""
    _, p2, p3, _, p5, p6 = pts
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / 2.0)


def _iris_center_radius(pts5: np.ndarray) -> tuple[np.ndarray, float]:
    """Iris center and radius (pixels) from 5 points (center first)."""
    center = pts5[0]
    ring = pts5[1:]
    radius = float(np.mean(np.linalg.norm(ring - center, axis=1)))
    return center, radius


class EyeTracker:
    """Wrapper around MediaPipe Tasks FaceLandmarker focused on blink detection."""

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
        """Run FaceLandmarker on an RGB frame and return smoothed EAR values.

        ``timestamp_ms`` must be monotonically increasing (VIDEO running mode).
        """
        h, w = frame_rgb.shape[:2]

        # FaceLandmarker VIDEO mode needs strictly increasing integer timestamps.
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

        def pts_for(indices) -> np.ndarray:
            return np.array([[lm[i].x * w, lm[i].y * h] for i in indices],
                            dtype=np.float32)

        left_pts = pts_for(config.LEFT_EYE_EAR)
        right_pts = pts_for(config.RIGHT_EYE_EAR)

        iris_left_draw = iris_right_draw = None
        metric = "ear"

        if config.USE_IRIS and len(lm) >= 478:
            # --- Iris-normalized openness: lid_gap / iris_diameter ---------
            cA, rA = _iris_center_radius(pts_for(config.IRIS_GROUP_A))
            cB, rB = _iris_center_radius(pts_for(config.IRIS_GROUP_B))

            left_centroid = left_pts.mean(axis=0)
            right_centroid = right_pts.mean(axis=0)

            # Match each iris group to the nearest eye (ignore MP's labels).
            if (np.linalg.norm(left_centroid - cA)
                    <= np.linalg.norm(left_centroid - cB)):
                (lc, lr), (rc, rr) = (cA, rA), (cB, rB)
            else:
                (lc, lr), (rc, rr) = (cB, rB), (cA, rA)

            diam_l = max(2.0 * lr, 1e-6)
            diam_r = max(2.0 * rr, 1e-6)
            raw_left = _lid_gap(left_pts) / diam_l
            raw_right = _lid_gap(right_pts) / diam_r
            metric = "iris"
            iris_left_draw = (int(lc[0]), int(lc[1]), int(round(lr)))
            iris_right_draw = (int(rc[0]), int(rc[1]), int(round(rr)))
        else:
            # --- Fallback: classic Eye Aspect Ratio ------------------------
            raw_left = _ear_from_points(left_pts)
            raw_right = _ear_from_points(right_pts)

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
            ear_left=sm_left,
            ear_right=sm_right,
            ear_avg=(sm_left + sm_right) / 2.0,
            ear_left_raw=raw_left,
            ear_right_raw=raw_right,
            metric=metric,
            left_ring=left_ring,
            right_ring=right_ring,
            iris_left=iris_left_draw,
            iris_right=iris_right_draw,
        )

    def close(self) -> None:
        self._landmarker.close()
