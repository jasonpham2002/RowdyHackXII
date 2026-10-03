"""FaceLandmarker wrapper that detects eye open/closed from EYELID SHAPE (EAR).

Openness is the classic Eye Aspect Ratio computed from the 6 eyelid landmarks
per eye:

    EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)

ZOOM MODE (optional, on by default): after the first detection we remember a
region of interest (ROI) around the eyes, then on the next frame we crop and
upscale just that region and run detection on it. This gives the eyes many more
pixels, which makes EAR much more accurate for small / narrow eyes. If detection
in the ROI fails we fall back to the full frame, so tracking is never lost.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import cv2
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
    # Pixel coordinates (full frame) for drawing eye outlines in the HUD.
    left_ring: List[Tuple[int, int]] = field(default_factory=list)
    right_ring: List[Tuple[int, int]] = field(default_factory=list)
    # The zoom region used for this detection (x, y, w, h), or None if full frame.
    roi: Optional[Tuple[int, int, int, int]] = None


def _ear_from_points(pts: np.ndarray) -> float:
    """Eye Aspect Ratio from the 6 ordered eyelid points (p1..p6)."""
    p1, p2, p3, p4, p5, p6 = pts
    vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    horizontal = 2.0 * np.linalg.norm(p1 - p4)
    if horizontal <= 1e-6:
        return 0.0
    return float(vertical / horizontal)


class EyeTracker:
    """FaceLandmarker-based Eye Aspect Ratio blink detector with eye-zoom."""

    def __init__(self, zoom: bool = True) -> None:
        if not config.MODEL_PATH.exists():
            raise SystemExit(
                f"Model not found at {config.MODEL_PATH}.\n"
                "Download it with:  python download_model.py"
            )
        base = mp_python.BaseOptions(model_asset_path=str(config.MODEL_PATH))
        options = vision.FaceLandmarkerOptions(
            base_options=base,
            running_mode=vision.RunningMode.IMAGE,   # we do our own ROI tracking
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._left_hist: deque[float] = deque(maxlen=config.SMOOTH_WINDOW)
        self._right_hist: deque[float] = deque(maxlen=config.SMOOTH_WINDOW)
        self.zoom_enabled = zoom
        self._roi: Optional[Tuple[int, int, int, int]] = None

    def toggle_zoom(self) -> bool:
        self.zoom_enabled = not self.zoom_enabled
        self._roi = None
        return self.zoom_enabled

    @staticmethod
    def _median(hist: deque[float]) -> float:
        return float(np.median(hist)) if hist else 0.0

    # ------------------------------------------------------------------ #
    def process(self, frame_rgb: np.ndarray, timestamp_ms: float) -> EyeReading:
        """Detect eyes, zooming into the eye region when possible."""
        reading: Optional[EyeReading] = None

        if self.zoom_enabled and self._roi is not None:
            reading = self._detect_in_roi(frame_rgb, self._roi)
            if reading is None or not reading.found:
                reading = None  # ROI miss -> fall back to full frame

        if reading is None:
            reading = self._detect_full(frame_rgb)

        # Update the ROI for the next frame from where the eyes actually are.
        if reading.found and self.zoom_enabled:
            self._roi = self._eye_roi(reading, frame_rgb.shape)
        elif not reading.found:
            self._roi = None

        return reading

    # ------------------------------------------------------------------ #
    def _detect_full(self, frame_rgb: np.ndarray) -> EyeReading:
        h, w = frame_rgb.shape[:2]
        lm = self._run(frame_rgb)
        if lm is None:
            return EyeReading(found=False)
        return self._reading_from(lm, lambda x, y: (x * w, y * h), roi=None)

    def _detect_in_roi(self, frame_rgb: np.ndarray,
                       roi: Tuple[int, int, int, int]) -> Optional[EyeReading]:
        x, y, w, h = roi
        crop = frame_rgb[y:y + h, x:x + w]
        if crop.size == 0:
            return None
        # Upscale the crop so the eyes get more pixels for the model.
        scale = max(1.0, 480.0 / max(w, h))
        if scale > 1.0:
            crop = cv2.resize(crop, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_LINEAR)
        lm = self._run(crop)
        if lm is None:
            return None
        # Normalized coords are relative to the crop == the ROI in the full frame.
        return self._reading_from(lm, lambda nx, ny: (x + nx * w, y + ny * h),
                                  roi=roi)

    def _run(self, image_rgb: np.ndarray):
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                            data=np.ascontiguousarray(image_rgb))
        result = self._landmarker.detect(mp_image)
        if not result.face_landmarks:
            return None
        return result.face_landmarks[0]

    def _reading_from(self, lm, to_px: Callable[[float, float], Tuple[float, float]],
                      roi) -> EyeReading:
        def pts_for(indices) -> np.ndarray:
            return np.array([to_px(lm[i].x, lm[i].y) for i in indices],
                            dtype=np.float32)

        raw_left = _ear_from_points(pts_for(config.LEFT_EYE_LIDS))
        raw_right = _ear_from_points(pts_for(config.RIGHT_EYE_LIDS))

        self._left_hist.append(raw_left)
        self._right_hist.append(raw_right)
        sm_left = self._median(self._left_hist)
        sm_right = self._median(self._right_hist)

        left_ring = [tuple(map(int, to_px(lm[i].x, lm[i].y)))
                     for i in config.LEFT_EYE_RING]
        right_ring = [tuple(map(int, to_px(lm[i].x, lm[i].y)))
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
            roi=roi,
        )

    @staticmethod
    def _eye_roi(reading: EyeReading, shape) -> Tuple[int, int, int, int]:
        """Square region centered on the eyes, scaled to the eye span.

        The eye span roughly tracks face size, so a square ~2.6x of it keeps
        enough face (forehead to mouth) for the detector to stay reliable while
        still zooming in on the eyes.
        """
        H, W = shape[:2]
        pts = reading.left_ring + reading.right_ring
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        bw = max(1, xmax - xmin)
        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0
        side = min(float(min(W, H)), max(120.0, bw * 2.6))
        x = int(round(cx - side / 2.0))
        y = int(round(cy - side / 2.0))
        x = max(0, min(x, W - int(side)))
        y = max(0, min(y, H - int(side)))
        return (x, y, int(side), int(side))

    def close(self) -> None:
        self._landmarker.close()
