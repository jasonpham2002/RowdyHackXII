"""Interactive calibration.

Captures the user's open-eye and closed-eye EAR distributions for a few seconds
each, then derives an adaptive per-eye ``close_thresh``. This is what makes the
detector robust across people and lighting.
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
    open_l: List[float] = []
    open_r: List[float] = []
    closed_l: List[float] = []
    closed_r: List[float] = []

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
                open_samples.append(reading.open_avg)
                open_l.append(reading.open_left)
                open_r.append(reading.open_right)
            elif name == "closed" and reading.found:
                closed_samples.append(reading.open_avg)
                closed_l.append(reading.open_left)
                closed_r.append(reading.open_right)

            _put(frame, "CALIBRATION", 60, (255, 255, 0), 1.2, 3)
            _put(frame, message, 110, color)
            _put(frame, f"{remaining:0.1f}s", 160, (255, 255, 255))
            if reading.found:
                _put(frame, f"openness: {reading.open_avg:0.3f}", 210,
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

    def compute_thresh(open_vals, closed_vals):
        """Adaptive close threshold for one eye (works for any eye size)."""
        o_arr = np.array(open_vals)
        c_arr = np.array(closed_vals)
        o_mean = float(np.median(o_arr))
        o_std = float(np.std(o_arr))
        c_mean = float(np.median(c_arr))
        # 60% of the way from open toward closed.
        t = o_mean - config.CLOSE_RATIO * (o_mean - c_mean)
        # Keep normal open-eye jitter above the line...
        t = min(t, o_mean - 3.0 * o_std)
        # ...but never dip to/below the measured closed level.
        t = max(t, c_mean + 0.01)
        return t, o_mean, c_mean

    t_left, ol_mean, cl_mean = compute_thresh(open_l, closed_l)
    t_right, orr_mean, cr_mean = compute_thresh(open_r, closed_r)
    open_mean = (ol_mean + orr_mean) / 2.0
    closed_mean = (cl_mean + cr_mean) / 2.0
    close_thresh = (t_left + t_right) / 2.0

    rc = config.RuntimeConfig(
        close_thresh=round(close_thresh, 4),
        min_open_drop=round(max(open_mean - closed_mean, config.DEFAULT_MIN_OPEN_DROP), 4),
        open_mean=round(open_mean, 4),
        closed_mean=round(closed_mean, 4),
        close_thresh_left=round(t_left, 4),
        close_thresh_right=round(t_right, 4),
    )
    return rc
