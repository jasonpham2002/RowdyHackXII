"""FaceLandmarker eye tracker with robust blink + gaze filtering.

Combines:
- existing 2D EAR
- 3D relative EAR blink detection
- MediaPipe eyeBlinkLeft / eyeBlinkRight
- MediaPipe eyeLookUp / eyeLookDown
- ROI eye zoom

The goal is to reject false blink signals caused by looking up/down.
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
except ImportError as exc:
    raise SystemExit(
        "mediapipe is required. Install dependencies with:\n"
        "    pip install -r requirements.txt"
    ) from exc

import config
from robust_blink_detector import Robust3DBlinkDetector


# ---------------------------------------------------------------------
# Fusion thresholds
#
# These are intentionally starting values.
# Later we will display the scores and tune them using YOUR camera.
# ---------------------------------------------------------------------

GAZE_BLOCK_THRESHOLD = 0.45
BLINK_CONFIRM_THRESHOLD = 0.40


@dataclass
class EyeReading:
    """One frame of eye measurements."""

    found: bool = False

    # Existing 2D EAR values
    open_left: float = 0.0
    open_right: float = 0.0
    open_avg: float = 0.0

    open_left_raw: float = 0.0
    open_right_raw: float = 0.0

    # Eye outlines for HUD
    left_ring: List[Tuple[int, int]] = field(default_factory=list)
    right_ring: List[Tuple[int, int]] = field(default_factory=list)

    # Zoom ROI
    roi: Optional[Tuple[int, int, int, int]] = None

    # -----------------------------------------------------------------
    # New robust blink information
    # -----------------------------------------------------------------

    ear_3d: float = 0.0
    relative_ear: float = 1.0

    blink_candidate: bool = False
    blink_detected: bool = False
    blink_duration_ms: float = 0.0

    # MediaPipe blendshape scores
    blink_left_score: float = 0.0
    blink_right_score: float = 0.0

    look_up_score: float = 0.0
    look_down_score: float = 0.0

    gaze_blocked: bool = False


def _ear_from_points(pts: np.ndarray) -> float:
    """Classic 2D Eye Aspect Ratio."""

    p1, p2, p3, p4, p5, p6 = pts

    vertical = (
        np.linalg.norm(p2 - p6)
        + np.linalg.norm(p3 - p5)
    )

    horizontal = (
        2.0 * np.linalg.norm(p1 - p4)
    )

    if horizontal <= 1e-6:
        return 0.0

    return float(vertical / horizontal)


class EyeTracker:
    """MediaPipe eye tracker with 3D blink + gaze filtering."""

    def __init__(self, zoom: bool = True) -> None:

        if not config.MODEL_PATH.exists():
            raise SystemExit(
                f"Model not found at {config.MODEL_PATH}.\n"
                "Download it with: python download_model.py"
            )

        base = mp_python.BaseOptions(
            model_asset_path=str(config.MODEL_PATH)
        )

        options = vision.FaceLandmarkerOptions(
            base_options=base,

            running_mode=vision.RunningMode.IMAGE,

            num_faces=1,

            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,

            # IMPORTANT:
            # enables eyeBlink and eyeLook blendshapes
            output_face_blendshapes=True,
        )

        self._landmarker = (
            vision.FaceLandmarker.create_from_options(options)
        )

        # Existing 2D EAR smoothing
        self._left_hist: deque[float] = deque(
            maxlen=config.SMOOTH_WINDOW
        )

        self._right_hist: deque[float] = deque(
            maxlen=config.SMOOTH_WINDOW
        )

        self.zoom_enabled = zoom

        self._roi: Optional[
            Tuple[int, int, int, int]
        ] = None

        # Robust paper-inspired blink detector
        self._robust_blink = Robust3DBlinkDetector(
            fps=30.0,
            candidate_threshold=0.90,
            depth_threshold=0.80,
            min_duration_ms=100.0,
            post_frames=2,
        )

        # Strongest MediaPipe blink evidence seen
        # during the current candidate.
        self._blink_peak_left = 0.0
        self._blink_peak_right = 0.0

    # -----------------------------------------------------------------

    def toggle_zoom(self) -> bool:

        self.zoom_enabled = not self.zoom_enabled

        self._roi = None

        return self.zoom_enabled

    # -----------------------------------------------------------------

    @staticmethod
    def _median(hist: deque[float]) -> float:

        if not hist:
            return 0.0

        return float(np.median(hist))

    # -----------------------------------------------------------------

    def process(
        self,
        frame_rgb: np.ndarray,
        timestamp_ms: float,
    ) -> EyeReading:

        reading: Optional[EyeReading] = None

        # Try zoom ROI first
        if (
            self.zoom_enabled
            and self._roi is not None
        ):

            reading = self._detect_in_roi(
                frame_rgb,
                self._roi,
                timestamp_ms,
            )

            if reading is None or not reading.found:
                reading = None

        # Fall back to whole frame
        if reading is None:

            reading = self._detect_full(
                frame_rgb,
                timestamp_ms,
            )

        # Update ROI for next frame
        if (
            reading.found
            and self.zoom_enabled
        ):

            self._roi = self._eye_roi(
                reading,
                frame_rgb.shape,
            )

        elif not reading.found:

            self._roi = None

        return reading

    # -----------------------------------------------------------------

    def _detect_full(
        self,
        frame_rgb: np.ndarray,
        timestamp_ms: float,
    ) -> EyeReading:

        h, w = frame_rgb.shape[:2]

        result = self._run(frame_rgb)

        if result is None:
            return EyeReading(found=False)

        landmarks, blend = result

        return self._reading_from(
            landmarks,
            blend,
            lambda x, y: (
                x * w,
                y * h,
            ),
            roi=None,
            timestamp_ms=timestamp_ms,
        )

    # -----------------------------------------------------------------

    def _detect_in_roi(
        self,
        frame_rgb: np.ndarray,
        roi: Tuple[int, int, int, int],
        timestamp_ms: float,
    ) -> Optional[EyeReading]:

        x, y, w, h = roi

        crop = frame_rgb[
            y:y + h,
            x:x + w
        ]

        if crop.size == 0:
            return None

        # Upscale the crop so eyes get more pixels.
        scale = max(
            1.0,
            480.0 / max(w, h),
        )

        if scale > 1.0:

            crop = cv2.resize(
                crop,
                (
                    int(w * scale),
                    int(h * scale),
                ),
                interpolation=cv2.INTER_LINEAR,
            )

        result = self._run(crop)

        if result is None:
            return None

        landmarks, blend = result

        return self._reading_from(
            landmarks,
            blend,
            lambda nx, ny: (
                x + nx * w,
                y + ny * h,
            ),
            roi=roi,
            timestamp_ms=timestamp_ms,
        )

    # -----------------------------------------------------------------

    def _run(self, image_rgb: np.ndarray):

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(image_rgb),
        )

        result = self._landmarker.detect(mp_image)

        if not result.face_landmarks:
            return None

        landmarks = result.face_landmarks[0]

        blend = {}

        if result.face_blendshapes:

            for category in result.face_blendshapes[0]:

                name = getattr(
                    category,
                    "category_name",
                    None,
                )

                if name:

                    blend[name] = float(
                        category.score
                    )

        return landmarks, blend

    # -----------------------------------------------------------------

    def _reading_from(
        self,
        lm,
        blend,
        to_px: Callable[
            [float, float],
            Tuple[float, float],
        ],
        roi,
        timestamp_ms: float,
    ) -> EyeReading:

        # =============================================================
        # Existing 2D EAR
        # =============================================================

        def pts_for(indices) -> np.ndarray:

            return np.array(
                [
                    to_px(
                        lm[i].x,
                        lm[i].y,
                    )
                    for i in indices
                ],
                dtype=np.float32,
            )

        raw_left = _ear_from_points(
            pts_for(
                config.LEFT_EYE_LIDS
            )
        )

        raw_right = _ear_from_points(
            pts_for(
                config.RIGHT_EYE_LIDS
            )
        )

        self._left_hist.append(
            raw_left
        )

        self._right_hist.append(
            raw_right
        )

        sm_left = self._median(
            self._left_hist
        )

        sm_right = self._median(
            self._right_hist
        )

        # =============================================================
        # Eye outlines for HUD
        # =============================================================

        left_ring = [
            tuple(
                map(
                    int,
                    to_px(
                        lm[i].x,
                        lm[i].y,
                    ),
                )
            )
            for i in config.LEFT_EYE_RING
        ]

        right_ring = [
            tuple(
                map(
                    int,
                    to_px(
                        lm[i].x,
                        lm[i].y,
                    ),
                )
            )
            for i in config.RIGHT_EYE_RING
        ]

        # =============================================================
        # MediaPipe blink scores
        # =============================================================

        blink_left = blend.get(
            "eyeBlinkLeft",
            0.0,
        )

        blink_right = blend.get(
            "eyeBlinkRight",
            0.0,
        )

        # Both eyes should agree for a real bilateral blink.
        bilateral_blink = min(
            blink_left,
            blink_right,
        )

        # =============================================================
        # MediaPipe vertical gaze
        # =============================================================

        look_up_left = blend.get(
            "eyeLookUpLeft",
            0.0,
        )

        look_up_right = blend.get(
            "eyeLookUpRight",
            0.0,
        )

        look_down_left = blend.get(
            "eyeLookDownLeft",
            0.0,
        )

        look_down_right = blend.get(
            "eyeLookDownRight",
            0.0,
        )

        # Average both eyes rather than trusting one noisy eye.
        look_up = (
            look_up_left
            + look_up_right
        ) / 2.0

        look_down = (
            look_down_left
            + look_down_right
        ) / 2.0

        vertical_gaze = max(
            look_up,
            look_down,
        )

        # =============================================================
        # Gaze rejection
        #
        # If gaze says UP/DOWN strongly, while MediaPipe does not think
        # both eyes are blinking, block the signal.
        # =============================================================

        gaze_blocked = (
            vertical_gaze >= GAZE_BLOCK_THRESHOLD
            and bilateral_blink < BLINK_CONFIRM_THRESHOLD
        )

        # =============================================================
        # Robust 3D detector
        # =============================================================

        if gaze_blocked:

            # Kill any EAR candidate caused by looking up/down.
            self._robust_blink.cancel_candidate()

            self._blink_peak_left = 0.0
            self._blink_peak_right = 0.0

            ear_3d = (
                self._robust_blink.calculate_3d_ear(
                    lm
                )
            )

            # We intentionally do NOT let gaze movement become
            # a low relative EAR signal.
            relative_ear = 1.0

            blink_candidate = False
            blink_event = None

        else:

            robust = self._robust_blink.update(
                lm,
                timestamp=(
                    timestamp_ms
                    / 1000.0
                ),
            )

            ear_3d = robust["ear"]

            relative_ear = robust[
                "relative_ear"
            ]

            if relative_ear is None:
                relative_ear = 1.0

            blink_candidate = bool(
                robust["candidate"]
            )

            blink_event = robust["blink"]

            # ---------------------------------------------------------
            # Save strongest blink scores during candidate
            # ---------------------------------------------------------

            if blink_candidate:

                self._blink_peak_left = max(
                    self._blink_peak_left,
                    blink_left,
                )

                self._blink_peak_right = max(
                    self._blink_peak_right,
                    blink_right,
                )

            # ---------------------------------------------------------
            # 3D detector says BLINK.
            # Require MediaPipe bilateral blink confirmation too.
            # ---------------------------------------------------------

            if blink_event is not None:

                self._blink_peak_left = max(
                    self._blink_peak_left,
                    blink_left,
                )

                self._blink_peak_right = max(
                    self._blink_peak_right,
                    blink_right,
                )

                bilateral_confirmed = (
                    self._blink_peak_left
                    >= BLINK_CONFIRM_THRESHOLD
                    and
                    self._blink_peak_right
                    >= BLINK_CONFIRM_THRESHOLD
                )

                if not bilateral_confirmed:

                    blink_event = None

                self._blink_peak_left = 0.0
                self._blink_peak_right = 0.0

            elif not blink_candidate:

                # Candidate disappeared without becoming a valid blink.
                self._blink_peak_left = 0.0
                self._blink_peak_right = 0.0

        # =============================================================
        # Final result
        # =============================================================

        blink_detected = (
            blink_event is not None
        )

        blink_duration_ms = (
            blink_event.duration_ms
            if blink_event is not None
            else 0.0
        )

        return EyeReading(
            found=True,

            # Existing EAR
            open_left=sm_left,
            open_right=sm_right,
            open_avg=(
                sm_left + sm_right
            ) / 2.0,

            open_left_raw=raw_left,
            open_right_raw=raw_right,

            # HUD
            left_ring=left_ring,
            right_ring=right_ring,
            roi=roi,

            # Robust blink system
            ear_3d=ear_3d,
            relative_ear=relative_ear,
            blink_candidate=blink_candidate,
            blink_detected=blink_detected,
            blink_duration_ms=blink_duration_ms,

            # MediaPipe evidence
            blink_left_score=blink_left,
            blink_right_score=blink_right,
            look_up_score=look_up,
            look_down_score=look_down,
            gaze_blocked=gaze_blocked,
        )

    # -----------------------------------------------------------------

    @staticmethod
    def _eye_roi(
        reading: EyeReading,
        shape,
    ) -> Tuple[int, int, int, int]:

        H, W = shape[:2]

        pts = (
            reading.left_ring
            + reading.right_ring
        )

        xs = [
            p[0]
            for p in pts
        ]

        ys = [
            p[1]
            for p in pts
        ]

        xmin = min(xs)
        xmax = max(xs)

        ymin = min(ys)
        ymax = max(ys)

        bw = max(
            1,
            xmax - xmin,
        )

        cx = (
            xmin + xmax
        ) / 2.0

        cy = (
            ymin + ymax
        ) / 2.0

        side = min(
            float(min(W, H)),
            max(
                120.0,
                bw * 2.6,
            ),
        )

        x = int(
            round(
                cx - side / 2.0
            )
        )

        y = int(
            round(
                cy - side / 2.0
            )
        )

        x = max(
            0,
            min(
                x,
                W - int(side),
            ),
        )

        y = max(
            0,
            min(
                y,
                H - int(side),
            ),
        )

        return (
            x,
            y,
            int(side),
            int(side),
        )

    # -----------------------------------------------------------------

    def close(self) -> None:

        self._landmarker.close()