"""FaceLandmarker wrapper that detects eye open/closed from EYELID SHAPE (EAR).

Openness is the classic Eye Aspect Ratio computed from the 6 eyelid landmarks
per eye:

    EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)

It drops sharply when the eyelids close. Values are smoothed with a short
rolling median so single-frame landmark jitter does not create phantom blinks.
No iris information is used.
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
    """One frame's worth of eye measurements (Eye Aspect Ratio)."""

    found: bool = False
    open_left: float = 0.0          # smoothed EAR, anatomical left eye
    open_right: float = 0.0         # smoothed EAR, anatomical right eye
    open_avg: float = 0.0
    open_left_raw: float = 0.0
    open_right_raw: float = 0.0
    # Pixel coordinates for drawing eye outlines in the HUD.
    left_ring: List[Tuple[int, int]] = field(default_factory=list)
    right_ring: List[Tuple[int, int]] = field(default_factory=list)


def _ear_from_points(pts: np.ndarray) -> float:
    """Eye Aspect Ratio from the 6 ordered eyelid points (p1..p6)."""
    p1, p2, p3, p4, p5, p6 = pts
    vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    horizontal = 2.0 * np.linalg.norm(p1 - p4)
    if horizontal <= 1e-6:
        return 0.0
    return float(vertical / horizontal)


class EyeTracker:
    """FaceLandmarker-based Eye Aspect Ratio blink detector."""

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
        """Run FaceLandmarker and return smoothed per-eye EAR.

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

        def pts_for(indices) -> np.ndarray:
            return np.array([[lm[i].x * w, lm[i].y * h] for i in indices],
                            dtype=np.float32)

        raw_left = _ear_from_points(pts_for(config.LEFT_EYE_LIDS))
        raw_right = _ear_from_points(pts_for(config.RIGHT_EYE_LIDS))

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
        )

    def close(self) -> None:
        self._landmarker.close()
