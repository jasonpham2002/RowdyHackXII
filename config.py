"""Central configuration for the eye-blink Morse decoder.

Every tunable number lives here so thresholds can be tweaked quickly during a
demo without hunting through the code. A small ``RuntimeConfig`` dataclass holds
the values that calibration overwrites at runtime (and that can be persisted to
``calibration.json``).

Eye open/closed is decided by the Eye Aspect Ratio (EAR) from the eyelid
landmarks. No iris information is used.
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
# Eyelid landmark indices for the Eye Aspect Ratio.
# Order: (p1, p2, p3, p4, p5, p6) where p1/p4 are the eye corners (horizontal)
# and the rest are top/bottom lids: EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|).
# --------------------------------------------------------------------------- #
# Anatomical RIGHT eye (appears on the LEFT of a mirrored frame).
RIGHT_EYE_LIDS = (33, 160, 158, 133, 153, 144)
# Anatomical LEFT eye (appears on the RIGHT of a mirrored frame).
LEFT_EYE_LIDS = (362, 385, 387, 263, 373, 380)

# Fuller contours (just for drawing a nice outline around each eye in the HUD).
RIGHT_EYE_RING = (33, 7, 163, 144, 145, 153, 154, 155, 133,
                  173, 157, 158, 159, 160, 161, 246)
LEFT_EYE_RING = (362, 382, 381, 380, 374, 373, 390, 249, 263,
                 466, 388, 387, 386, 385, 384, 398)

# --------------------------------------------------------------------------- #
# EAR smoothing
# --------------------------------------------------------------------------- #
SMOOTH_WINDOW = 5           # rolling median window (frames) to kill jitter

# --------------------------------------------------------------------------- #
# Blink / wink timing (milliseconds). These drive the state machine.
# --------------------------------------------------------------------------- #
BLINK_MIN_MS = 40           # closures shorter than this are ignored (noise)
DOT_MAX_MS = 250            # 40..250 ms (both eyes) -> DOT, longer -> DASH
LETTER_GAP_MS = 700         # eyes open this long -> commit the current letter
WORD_GAP_MS = 2000          # still detected; a pause no longer inserts a space
WINK_MIN_MS = 300           # a single eye must stay closed this long to count as a wink
RIGHT_PICK_MAX_MS = 1000    # a right blink longer than this does not count toward a suggestion
RIGHT_SELECT_GAP_MS = 3000  # pause after the last right blink before that suggestion is chosen

# Shortcut matching (Assist mode). SOS is three fast dots, not the letter S.
SOS_MAX_GAP_MS = 400        # max time between blinks inside a fast shortcut
SOS_MAX_SPAN_MS = 1500      # whole three-dot gesture must finish inside this
SHORTCUT_HOLD_MS = 1000     # wait after the last blink so a longer pattern can win
ASSIST_SHOW_S = 5.0         # how long an assist message stays on screen
WORKSPACE_PORT = 8765
ROOM_PORT = 8766
ROOM_SESSION_FILE = Path(__file__).with_name("room_session.json")
SHORTCUTS_FILE = Path(__file__).with_name("shortcuts.json")
DISPATCH_LOG = Path(__file__).with_name("dispatch_log.txt")
BOTH_CONFIRM_FRAMES = 2     # consecutive frames of "both closed" to treat as a blink

# --------------------------------------------------------------------------- #
# Calibration defaults (overwritten after running calibration).
# EAR is roughly ~0.3 open / ~0.08 closed (varies a lot with eye shape).
# --------------------------------------------------------------------------- #
DEFAULT_CLOSE_THRESH = 0.22     # EAR below this == eye considered closed
DEFAULT_MIN_OPEN_DROP = 0.06    # min open->closed EAR drop for calibration to trust itself
# Higher threshold == a lighter wink counts as closed. The ratio places the
# line between the open and closed measurements; lower ratio keeps it closer
# to the open value.
CLOSE_RATIO = 0.62              # close_thresh sits 62% of the way from open toward closed
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
    open_mean: float = 0.30
    closed_mean: float = 0.08
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
