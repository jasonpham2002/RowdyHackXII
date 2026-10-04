"""Offline smoke tests (no camera needed).

Run:  python test_smoke.py
Exercises Morse decoding, word prediction, the blink/wink state machine via a
simulated openness timeline, and confirms the FaceLandmarker model loads and
runs on a synthetic frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import config
import morse
from predictor import WordPredictor
from state_machine import BlinkStateMachine, Event


@dataclass
class FakeReading:
    found: bool = True
    open_left: float = 0.45
    open_right: float = 0.45
    open_avg: float = 0.45


def _run(machine, left, right, start_ms, duration_ms, step=30):
    """Feed frames with given per-eye openness for a span, return events."""
    events = []
    t = start_ms
    end = start_ms + duration_ms
    while t <= end:
        r = FakeReading(open_left=left, open_right=right,
                        open_avg=(left + right) / 2)
        events += machine.update(r, t)
        t += step
    return events, t


def test_morse():
    assert morse.decode(".-") == "A"
    assert morse.decode("...") == "S"
    assert morse.decode("-----") == "0"
    assert morse.decode("......") is None   # unknown
    assert morse.encode("A") == ".-"
    assert len(morse.reference_rows()) == 36
    print("[ok] morse table")


def test_predictor():
    p = WordPredictor()
    sug = p.predict("hel")
    assert any(w.startswith("hel") for w in sug), sug
    assert p.predict("") == []
    print(f"[ok] predictor (hel -> {sug})")


def test_state_machine():
    rc = config.RuntimeConfig(close_thresh=0.21)
    m = BlinkStateMachine(rc)
    closed, openv = 0.10, 0.30

    # Open baseline.
    _run(m, openv, openv, 0, 60)
    # Short both-eyes blink (~60 ms) -> DOT.
    ev, t = _run(m, closed, closed, 100, 30)
    ev2, t = _run(m, openv, openv, t, 60)   # reopen
    got = ev + ev2
    assert Event.DOT in got, got
    print("[ok] dot detected")

    # Long both-eyes blink (~540 ms) -> DASH.
    ev, t = _run(m, closed, closed, t + 100, 540)
    ev2, t = _run(m, openv, openv, t, 60)
    assert Event.DASH in (ev + ev2), (ev + ev2)
    print("[ok] dash detected")

    # Hold eyes open past the 2s word gap -> LETTER_GAP then WORD_GAP.
    ev, t = _run(m, openv, openv, t, 2200)
    assert Event.LETTER_GAP in ev, ev
    assert Event.WORD_GAP in ev, ev
    print("[ok] letter gap + word gap")

    # Left wink (> 300 ms, right eye open) -> WINK_LEFT.
    m2 = BlinkStateMachine(rc)
    _run(m2, openv, openv, 0, 60)
    ev, t = _run(m2, closed, openv, 100, 400)
    ev2, t = _run(m2, openv, openv, t, 60)
    assert Event.WINK_LEFT in (ev + ev2), (ev + ev2)
    print("[ok] left wink")

    # Right blink (~330 ms) counts toward a suggestion. Longer than 1 s does not.
    m3 = BlinkStateMachine(rc)
    _run(m3, openv, openv, 0, 60)
    ev, t = _run(m3, openv, closed, 100, 300)
    ev2, t = _run(m3, openv, openv, t, 60)
    assert Event.WINK_RIGHT in (ev + ev2), (ev + ev2)
    m3b = BlinkStateMachine(rc)
    _run(m3b, openv, openv, 0, 60)
    ev, t = _run(m3b, openv, closed, 100, 1100)
    ev2, t = _run(m3b, openv, openv, t, 60)
    assert Event.WINK_RIGHT not in (ev + ev2), (ev + ev2)
    print("[ok] right wink")

    # Natural (too-short) blink is ignored.
    m4 = BlinkStateMachine(rc)
    _run(m4, openv, openv, 0, 60)
    ev, t = _run(m4, closed, closed, 100, 0)   # ~30 ms, under the ignore floor
    ev2, t = _run(m4, openv, openv, t, 60)
    assert Event.DOT not in (ev + ev2) and Event.DASH not in (ev + ev2)
    print("[ok] natural blink ignored")


def test_tracker_loads():
    from tracker import EyeTracker

    tr = EyeTracker()
    blank = np.zeros((config.FRAME_HEIGHT, config.FRAME_WIDTH, 3), dtype=np.uint8)
    reading = tr.process(blank, 0.0)
    assert reading.found is False   # no face in a blank frame
    reading2 = tr.process(blank, 33.0)
    assert reading2.found is False
    tr.close()
    print("[ok] FaceLandmarker loads and runs")


if __name__ == "__main__":
    test_morse()
    test_predictor()
    test_state_machine()
    test_tracker_loads()
    print("\nAll smoke tests passed.")
