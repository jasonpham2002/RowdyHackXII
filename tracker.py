"""FaceLandmarker wrapper that turns a camera frame into per-eye openness.

Openness is measured with the IRIS method: ``eyelid_gap / iris_diameter``.
Because the iris is a near-constant physical size, this is robust to eye shape
and to viewing distance. Values are smoothed with a short rolling median so
single-frame landmark jitter does not create phantom blinks.
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
    """One frame's worth of eye measurements (iris openness)."""

    found: bool = False
    open_left: float = 0.0          # smoothed openness, anatomical left eye
    open_right: float = 0.0         # smoothed openness, anatomical right eye
    open_avg: float = 0.0
    open_left_raw: float = 0.0
    open_right_raw: float = 0.0
    # Pixel coordinates for drawing eye outlines in the HUD.
    left_ring: List[Tuple[int, int]] = field(default_factory=list)
    right_ring: List[Tuple[int, int]] = field(default_factory=list)
    # Iris circles (cx, cy, radius) in pixels, for drawing.
    iris_left: Tuple[int, int, int] | None = None
    iris_right: Tuple[int, int, int] | None = None


def _lid_gap(pts: np.ndarray) -> float:
    """Average vertical eyelid distance (pixels) from the 6 eyelid points."""
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
        """Run FaceLandmarker on an RGB frame and return smoothed openness.

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
        if len(lm) < 478:
            # The refined mesh (with iris) is required for this app.
            raise SystemExit(
                "FaceLandmarker did not return iris landmarks (need 478 points). "
                "Re-download the model with:  python download_model.py"
            )

        def pts_for(indices) -> np.ndarray:
            return np.array([[lm[i].x * w, lm[i].y * h] for i in indices],
                            dtype=np.float32)

        left_pts = pts_for(config.LEFT_EYE_LIDS)
        right_pts = pts_for(config.RIGHT_EYE_LIDS)

        # Iris-normalized openness: eyelid_gap / iris_diameter.
        cA, rA = _iris_center_radius(pts_for(config.IRIS_GROUP_A))
        cB, rB = _iris_center_radius(pts_for(config.IRIS_GROUP_B))

        left_centroid = left_pts.mean(axis=0)

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
