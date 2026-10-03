"""Interactive calibration.

Captures the user's open-eye and closed-eye EAR distributions for a few seconds
each, then derives an adaptive ``close_thresh`` plus a sanity ``min_ear_drop``
floor. This is what makes the detector robust across people and lighting.
"""

from __future__ import annotations

import time
from typing import List, Optional

import cv2
import numpy as np

import config
from tracker import EyeTracker


def _put(frame, text, y, color=(255, 255, 255), scale=0.9, thick=2):
    cv2.putText(frame, text, (30, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(frame, text, (30, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, thick, cv2.LINE_AA)


def _grab(cap):
    ok, frame = cap.read()
    if not ok:
        return None
    if config.FLIP_HORIZONTAL:
        frame = cv2.flip(frame, 1)
    return frame


def run_calibration(cap, tracker: EyeTracker,
                    window_name: str) -> Optional[config.RuntimeConfig]:
    """Guide the user through calibration. Returns ``None`` if aborted (ESC)."""

    phases = [
        ("countdown", config.CALIB_COUNTDOWN_SECONDS,
         "Get ready - keep your head still", (0, 220, 255)),
        ("open", config.CALIB_OPEN_SECONDS,
         "Keep your eyes OPEN and look at the camera", (0, 230, 0)),
        ("ready_close", config.CALIB_COUNTDOWN_SECONDS,
         "Now get ready to CLOSE your eyes", (0, 220, 255)),
        ("closed", config.CALIB_CLOSED_SECONDS,
         "CLOSE your eyes gently until it beeps", (0, 160, 255)),
    ]

    open_samples: List[float] = []
    closed_samples: List[float] = []

    for name, duration, message, color in phases:
        start = time.perf_counter()
        while True:
            frame = _grab(cap)
            if frame is None:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            reading = tracker.process(rgb, time.perf_counter() * 1000.0)

            elapsed = time.perf_counter() - start
            remaining = max(0.0, duration - elapsed)

            if name == "open" and reading.found:
                open_samples.append(reading.ear_avg)
            elif name == "closed" and reading.found:
                closed_samples.append(reading.ear_avg)

            _put(frame, "CALIBRATION", 60, (255, 255, 0), 1.2, 3)
            _put(frame, message, 110, color)
            _put(frame, f"{remaining:0.1f}s", 160, (255, 255, 255))
            if reading.found:
                _put(frame, f"EAR: {reading.ear_avg:0.3f}", 210,
                     (200, 200, 200), 0.7, 2)
            else:
                _put(frame, "No face detected", 210, (0, 0, 255), 0.7, 2)
            _put(frame, "ESC to skip (use defaults)", frame.shape[0] - 30,
                 (180, 180, 180), 0.6, 1)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                return None
            if remaining <= 0.0:
                break

    if len(open_samples) < 5 or len(closed_samples) < 5:
        # Not enough data; fall back to defaults.
        return None

    open_arr = np.array(open_samples)
    closed_arr = np.array(closed_samples)
    open_mean = float(np.median(open_arr))
    open_std = float(np.std(open_arr))
    closed_mean = float(np.median(closed_arr))

    # Primary threshold: 60% of the way from open toward closed.
    close_thresh = open_mean - config.CLOSE_RATIO * (open_mean - closed_mean)
    # Never let normal open-eye jitter cross the threshold.
    close_thresh = min(close_thresh, open_mean - 3.0 * open_std)
    # Never dip at or below the measured closed level.
    close_thresh = max(close_thresh, closed_mean + 0.01)

    rc = config.RuntimeConfig(
        close_thresh=round(close_thresh, 4),
        min_ear_drop=round(max(open_mean - closed_mean, config.DEFAULT_MIN_EAR_DROP), 4),
        open_mean=round(open_mean, 4),
        closed_mean=round(closed_mean, 4),
    )
    return rc
