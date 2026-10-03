"""Central configuration for the eye-blink Morse decoder.

Every tunable number lives here so thresholds can be tweaked quickly during a
demo without hunting through the code. A small ``RuntimeConfig`` dataclass holds
the values that calibration overwrites at runtime (and that can be persisted to
``calibration.json``).

Eye open/closed is decided purely by IRIS VISIBILITY: we look at the image
pixels where the iris should be and measure how clearly the iris/pupil is there
(dark center + local contrast). Eye shape is never used for detection.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# Camera
# --------------------------------------------------------------------------- #
CAMERA_INDEX = 0
FRAME_WIDTH = 1280          # 720p HD -> 1280x720
FRAME_HEIGHT = 720
FLIP_HORIZONTAL = True      # mirror the frame so it feels like a selfie view

# --------------------------------------------------------------------------- #
# Eye contour landmarks. These are used ONLY to draw an outline in the HUD and
# to locate the eye close-up inset. Detection does NOT use eye shape at all.
# --------------------------------------------------------------------------- #
RIGHT_EYE_RING = (33, 7, 163, 144, 145, 153, 154, 155, 133,
                  173, 157, 158, 159, 160, 161, 246)
LEFT_EYE_RING = (362, 382, 381, 380, 374, 373, 390, 249, 263,
                 466, 388, 387, 386, 385, 384, 398)

# --------------------------------------------------------------------------- #
# Iris landmarks (require the 478-point refined mesh, center listed first).
# We don't trust MediaPipe's left/right labels; each iris group is matched to
# the nearest eye at runtime.
# --------------------------------------------------------------------------- #
IRIS_GROUP_A = (468, 469, 470, 471, 472)   # center, then 4 ring points
IRIS_GROUP_B = (473, 474, 475, 476, 477)

# --------------------------------------------------------------------------- #
# Openness smoothing
# --------------------------------------------------------------------------- #
SMOOTH_WINDOW = 5           # rolling median window (frames) to kill jitter

# --------------------------------------------------------------------------- #
# Blink / wink timing (milliseconds). These drive the state machine.
# --------------------------------------------------------------------------- #
BLINK_MIN_MS = 120          # closures shorter than this are ignored (natural blink)
DOT_MAX_MS = 450            # 120..450 ms (both eyes) -> DOT, longer -> DASH
LETTER_GAP_MS = 700         # eyes open this long -> commit the current letter
WORD_GAP_MS = 1500          # eyes open this long -> commit letter + insert space
WINK_MIN_MS = 300           # a single eye must stay closed this long to count as a wink
BOTH_CONFIRM_FRAMES = 2     # consecutive frames of "both closed" to treat as a blink

# --------------------------------------------------------------------------- #
# Calibration defaults (overwritten after running calibration).
# openness = iris visibility (darkness + local contrast), ~0.5 open / ~0.05 closed.
# --------------------------------------------------------------------------- #
DEFAULT_CLOSE_THRESH = 0.25     # iris visibility below this == eye considered closed
DEFAULT_MIN_OPEN_DROP = 0.10    # min open->closed drop for calibration to trust itself
CLOSE_RATIO = 0.6               # close_thresh sits 60% of the way from open mean toward closed
CALIB_OPEN_SECONDS = 4.0
CALIB_CLOSED_SECONDS = 2.5
CALIB_COUNTDOWN_SECONDS = 2.0

# --------------------------------------------------------------------------- #
# Prediction / UI
# --------------------------------------------------------------------------- #
NUM_SUGGESTIONS = 3
VOCAB_SIZE = 50000          # how many English words to load from wordfreq
AUDIO_CUES = True           # beep on dot/dash (Windows winsound; silently ignored elsewhere)

CALIBRATION_FILE = Path(__file__).with_name("calibration.json")

# FaceLandmarker model (MediaPipe Tasks API). Download with:
#   python download_model.py
MODEL_PATH = Path(__file__).with_name("models") / "face_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


@dataclass
class RuntimeConfig:
    """Values that calibration tunes per-user / per-lighting at runtime.

    Per-eye thresholds (``close_thresh_left`` / ``close_thresh_right``) make the
    detector work for small or asymmetric eyes: each eye is judged against its
    own open/closed range instead of one global cutoff.
    """

    close_thresh: float = DEFAULT_CLOSE_THRESH          # combined (for HUD/display)
    min_open_drop: float = DEFAULT_MIN_OPEN_DROP
    open_mean: float = 0.50
    closed_mean: float = 0.05
    close_thresh_left: Optional[float] = None
    close_thresh_right: Optional[float] = None

    def __post_init__(self) -> None:
        if self.close_thresh_left is None:
            self.close_thresh_left = self.close_thresh
        if self.close_thresh_right is None:
            self.close_thresh_right = self.close_thresh

    def nudge(self, delta: float) -> None:
        """Shift all thresholds (live sensitivity tuning). Lower == eyes stay
        'open' at smaller openings (fixes "I must open too wide")."""
        lo, hi = 0.04, 0.9
        self.close_thresh = min(hi, max(lo, self.close_thresh + delta))
        self.close_thresh_left = min(hi, max(lo, (self.close_thresh_left or 0) + delta))
        self.close_thresh_right = min(hi, max(lo, (self.close_thresh_right or 0) + delta))

    def save(self, path: Path = CALIBRATION_FILE) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path = CALIBRATION_FILE) -> "RuntimeConfig | None":
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return cls(**data)
        except (ValueError, TypeError):
            return None
