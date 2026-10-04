"""Blink / wink timing state machine.

Converts a stream of per-eye openness readings into discrete events:

    DOT, DASH          - a both-eyes closure, classified by how long it was held
    LETTER_GAP         - eyes stayed open long enough to end the current letter
    WORD_GAP           - eyes stayed open even longer -> word break (space)
    WINK_LEFT          - only the left eye closed (held) -> backspace
    WINK_RIGHT         - only the right eye closed (held) -> count a suggestion pick

The design is "episode" based. A closure episode starts when *any* eye drops
below the close threshold and ends when *both* eyes are open again. During the
episode we remember whether both eyes were ever closed together (a blink) or
only one (a wink). This makes the detector robust to the fact that people never
close both eyelids on the exact same frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional

import config


class Event(Enum):
    DOT = auto()
    DASH = auto()
    LETTER_GAP = auto()
    WORD_GAP = auto()
    WINK_LEFT = auto()
    WINK_RIGHT = auto()


@dataclass
class MachineState:
    """Lightweight snapshot used by the HUD."""

    left_closed: bool = False
    right_closed: bool = False
    in_episode: bool = False
    episode_both: bool = False
    # How long (ms) the current closure has lasted, for a live progress bar.
    closure_ms: float = 0.0


class BlinkStateMachine:
    def __init__(self, runtime: config.RuntimeConfig) -> None:
        self.runtime = runtime

        # Closure episode tracking.
        self._in_episode = False
        self._episode_start = 0.0
        self._both_seen = False
        self._both_frames = 0
        self._left_seen = False
        self._right_seen = False

        # Open-gap tracking (after the last blink closure ended).
        self._last_close_end: Optional[float] = None
        self._awaiting_commit = False     # a dot/dash is pending commit
        self._letter_committed = False
        self._word_committed = False

        self.state = MachineState()

    def reset_gaps(self) -> None:
        """Called by the text layer after it consumes a letter/word gap."""
        self._awaiting_commit = False
        self._letter_committed = False
        self._word_committed = False
        self._last_close_end = None

    def update(self, reading, now_ms: float) -> List[Event]:
        """Feed one frame. ``now_ms`` is a monotonic timestamp in milliseconds."""
        events: List[Event] = []

        if reading.found:
            left_closed = reading.open_left < self.runtime.close_thresh_left
            right_closed = reading.open_right < self.runtime.close_thresh_right
        else:
            # No face: treat as "eyes open" so we don't accumulate a closure.
            left_closed = right_closed = False

        any_closed = left_closed or right_closed
        both_closed = left_closed and right_closed

        self.state.left_closed = left_closed
        self.state.right_closed = right_closed

        # ---- Episode start -------------------------------------------------
        if not self._in_episode and any_closed:
            self._in_episode = True
            self._episode_start = now_ms
            self._both_seen = False
            self._both_frames = 0
            self._left_seen = left_closed
            self._right_seen = right_closed

        # ---- During an episode --------------------------------------------
        if self._in_episode:
            self._left_seen |= left_closed
            self._right_seen |= right_closed
            if both_closed:
                self._both_frames += 1
                if self._both_frames >= config.BOTH_CONFIRM_FRAMES:
                    self._both_seen = True
            else:
                self._both_frames = 0

            self.state.in_episode = True
            self.state.episode_both = self._both_seen
            self.state.closure_ms = now_ms - self._episode_start

            # ---- Episode end (both eyes open again) -----------------------
            if not any_closed:
                duration = now_ms - self._episode_start
                ev = self._classify_episode(duration)
                if ev is not None:
                    events.append(ev)
                self._in_episode = False
                self.state.in_episode = False
                self.state.closure_ms = 0.0
                self._last_close_end = now_ms
            return events

        # ---- Open gap handling (no active closure) ------------------------
        self.state.in_episode = False
        self.state.closure_ms = 0.0

        if self._awaiting_commit and self._last_close_end is not None:
            open_ms = now_ms - self._last_close_end
            if not self._letter_committed and open_ms >= config.LETTER_GAP_MS:
                events.append(Event.LETTER_GAP)
                self._letter_committed = True
            if not self._word_committed and open_ms >= config.WORD_GAP_MS:
                events.append(Event.WORD_GAP)
                self._word_committed = True

        return events

    # ------------------------------------------------------------------ #
    def _classify_episode(self, duration: float) -> Optional[Event]:
        """Decide what a finished closure episode means."""
        if self._both_seen:
            # Both-eyes blink -> dot or dash by duration.
            if duration < config.BLINK_MIN_MS:
                return None  # involuntary / too short, ignore
            self._awaiting_commit = True
            self._letter_committed = False
            self._word_committed = False
            if duration <= config.DOT_MAX_MS:
                return Event.DOT
            return Event.DASH

        # Single-eye closure -> wink (only if held long enough).
        if duration < config.WINK_MIN_MS:
            return None
        if self._left_seen and not self._right_seen:
            return Event.WINK_LEFT
        if self._right_seen and not self._left_seen:
            return Event.WINK_RIGHT
        return None
