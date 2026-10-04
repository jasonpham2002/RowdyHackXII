from collections import deque
from dataclasses import dataclass
from typing import Optional, Sequence
import math
import time


RIGHT_EYE = {
    "corners": (33, 133),
    "vertical": (
        (160, 144),
        (158, 153),
        (159, 145),
    ),
}

LEFT_EYE = {
    "corners": (263, 362),
    "vertical": (
        (387, 373),
        (385, 380),
        (386, 374),
    ),
}


@dataclass
class BlinkEvent:
    start_time: float
    end_time: float
    duration_ms: float
    min_relative_ear: float


class Robust3DBlinkDetector:

    def __init__(
        self,
        fps: float = 30.0,
        candidate_threshold: float = 0.90,
        depth_threshold: float = 0.80,
        min_duration_ms: float = 100.0,
        post_frames: int = 2,
    ):
        self.fps = max(float(fps), 1.0)

        self.candidate_threshold = candidate_threshold
        self.depth_threshold = depth_threshold
        self.min_duration_ms = min_duration_ms
        self.post_frames = post_frames

        # About 2 seconds of EAR history
        self.history = deque(
            maxlen=max(5, int(round(2 * self.fps)))
        )

        self.candidate = []

        self.in_candidate = False
        self.frames_after_threshold = 0

        self.last_event: Optional[BlinkEvent] = None

    @staticmethod
    def _xyz(point):
        return (
            float(point.x),
            float(point.y),
            float(getattr(point, "z", 0.0)),
        )

    @classmethod
    def _dist3(cls, a, b):
        ax, ay, az = cls._xyz(a)
        bx, by, bz = cls._xyz(b)

        return math.sqrt(
            (bx - ax) ** 2
            + (by - ay) ** 2
            + (bz - az) ** 2
        )

    @classmethod
    def _eye_ear(cls, landmarks, eye):

        corner_a, corner_b = eye["corners"]

        horizontal = cls._dist3(
            landmarks[corner_a],
            landmarks[corner_b],
        )

        if horizontal <= 1e-9:
            return float("nan")

        vertical_sum = sum(
            cls._dist3(
                landmarks[top],
                landmarks[bottom],
            )
            for top, bottom in eye["vertical"]
        )

        return vertical_sum / (3.0 * horizontal)

    @classmethod
    def calculate_3d_ear(cls, landmarks):

        left = cls._eye_ear(
            landmarks,
            LEFT_EYE,
        )

        right = cls._eye_ear(
            landmarks,
            RIGHT_EYE,
        )

        if (
            not math.isfinite(left)
            or not math.isfinite(right)
        ):
            return float("nan")

        return (left + right) / 2.0

    @staticmethod
    def _flank_validation(values):

        if len(values) < 5:
            return False

        # Find lowest point of blink
        min_i = min(
            range(len(values)),
            key=values.__getitem__,
        )

        left = values[: min_i + 1]
        right = values[min_i:]

        if len(left) < 2 or len(right) < 2:
            return False

        left_frames = len(left) - 1
        right_frames = len(right) - 1

        # One side should not be >3x longer
        ratio = max(
            left_frames,
            right_frames,
        ) / max(
            1,
            min(
                left_frames,
                right_frames,
            ),
        )

        if ratio > 3.0:
            return False

        # Blink should go DOWN then UP
        left_diffs = [
            left[i + 1] - left[i]
            for i in range(len(left) - 1)
        ]

        right_diffs = [
            right[i + 1] - right[i]
            for i in range(len(right) - 1)
        ]

        falling_fraction = (
            sum(
                diff <= 0.02
                for diff in left_diffs
            )
            / len(left_diffs)
        )

        rising_fraction = (
            sum(
                diff >= -0.02
                for diff in right_diffs
            )
            / len(right_diffs)
        )

        if falling_fraction < 0.70:
            return False

        if rising_fraction < 0.70:
            return False

        fall_mag = (
            abs(left[-1] - left[0])
            / max(1, left_frames)
        )

        rise_mag = (
            abs(right[-1] - right[0])
            / max(1, right_frames)
        )

        if fall_mag <= 1e-6:
            return False

        if rise_mag <= 1e-6:
            return False

        gradient_ratio = max(
            fall_mag,
            rise_mag,
        ) / min(
            fall_mag,
            rise_mag,
        )

        if gradient_ratio > 4.0:
            return False

        return True

    def _validate_candidate(self):

        if not self.candidate:
            return None

        timestamps = [
            item[0]
            for item in self.candidate
        ]

        values = [
            item[1]
            for item in self.candidate
        ]

        duration_ms = (
            timestamps[-1]
            - timestamps[0]
        ) * 1000.0

        # Paper condition:
        # blink candidate >= 100 ms
        if duration_ms < self.min_duration_ms:
            return None

        maximum = max(values)
        minimum = min(values)

        if maximum <= 1e-9:
            return None

        # Paper condition:
        # min(candidate) / max(candidate) < 0.8
        if (
            minimum / maximum
        ) >= self.depth_threshold:
            return None

        # Check blink shape
        if not self._flank_validation(values):
            return None

        return BlinkEvent(
            start_time=timestamps[0],
            end_time=timestamps[-1],
            duration_ms=duration_ms,
            min_relative_ear=minimum,
        )

    def cancel_candidate(self):
        """Cancel a possible blink without deleting the rolling EAR baseline."""
        self.candidate = []
        self.in_candidate = False
        self.frames_after_threshold = 0


    def update(
        self,
        landmarks: Sequence,
        timestamp: Optional[float] = None,
    ):

        if timestamp is None:
            timestamp = time.perf_counter()

        ear = self.calculate_3d_ear(
            landmarks
        )

        if not math.isfinite(ear):
            return {
                "ear": ear,
                "relative_ear": None,
                "candidate": self.in_candidate,
                "blink": None,
            }

        # Compare current EAR against recent
        # approximately 2 second maximum.
        if self.history:
            rolling_max = max(
                self.history
            )
        else:
            rolling_max = ear

        if rolling_max > 1e-9:
            relative_ear = (
                ear / rolling_max
            )
        else:
            relative_ear = 1.0

        self.history.append(ear)

        emitted = None

        # Below 0.90 means possible blink
        if (
            relative_ear
            < self.candidate_threshold
        ):

            if not self.in_candidate:
                self.in_candidate = True
                self.candidate = []
                self.frames_after_threshold = 0

            self.candidate.append(
                (
                    timestamp,
                    relative_ear,
                )
            )

        elif self.in_candidate:

            # Add a couple frames after
            # threshold recovery
            self.candidate.append(
                (
                    timestamp,
                    relative_ear,
                )
            )

            self.frames_after_threshold += 1

            if (
                self.frames_after_threshold
                >= self.post_frames
            ):

                emitted = (
                    self._validate_candidate()
                )

                self.in_candidate = False
                self.candidate = []
                self.frames_after_threshold = 0

                if emitted is not None:
                    self.last_event = emitted

        return {
            "ear": ear,
            "relative_ear": relative_ear,
            "candidate": self.in_candidate,
            "blink": emitted,
        }