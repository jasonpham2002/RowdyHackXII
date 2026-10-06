"""Matcher tests for blink shortcuts. No camera required."""

from __future__ import annotations

import tempfile
from pathlib import Path

from actions import ActionRunner
from shortcuts import Shortcut, ShortcutMatcher, pattern_owner


def _matcher(tmp: Path) -> ShortcutMatcher:
    src = Path(__file__).with_name("shortcuts.json")
    tmp.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return ShortcutMatcher(tmp)


def test_fast_three_dots_match_sos():
    with tempfile.TemporaryDirectory() as folder:
        matcher = _matcher(Path(folder) / "shortcuts.json")
        assert matcher.push(".", 0) is None
        assert matcher.push(".", 200) is None
        assert matcher.push(".", 400) is None
        assert matcher.poll(400) is None
        hit = matcher.poll(1400)
        assert hit is not None and hit.action == "sos"
        assert matcher.poll(1500) is None


def test_slow_dots_do_not_match_sos():
    with tempfile.TemporaryDirectory() as folder:
        matcher = _matcher(Path(folder) / "shortcuts.json")
        matcher.push(".", 0)
        matcher.push(".", 900)
        matcher.push(".", 1800)
        assert matcher.poll(2800) is None


def test_three_dashes_match_hello_world():
    with tempfile.TemporaryDirectory() as folder:
        matcher = _matcher(Path(folder) / "shortcuts.json")
        # Each dash is held 600 ms, with a 400 ms open pause between them.
        assert matcher.push("-", 600, 600) is None
        assert matcher.push("-", 1600, 600) is None
        assert matcher.push("-", 2600, 600) is None
        assert matcher.poll(2600) is None
        hit = matcher.poll(3600)
        assert hit is not None and hit.name == "Hello World"
        assert hit.action == "message"


def test_longer_pattern_wins_after_pause():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "shortcuts.json"
        path.write_text(
            '{"demo_location":"x","shortcuts":['
            '{"name":"SOS","pattern":"...","max_gap_ms":400,"max_span_ms":2000,'
            '"action":"sos","message":"","destination":""},'
            '{"name":"Hello World","pattern":"....","max_gap_ms":400,"max_span_ms":2500,'
            '"action":"message","message":"Hello World","destination":""}'
            "]}",
            encoding="utf-8",
        )
        matcher = ShortcutMatcher(path)
        for t in (0, 200, 400, 600):
            assert matcher.push(".", t) is None
        assert matcher.poll(600) is None
        hit = matcher.poll(1600)
        assert hit is not None and hit.name == "Hello World"
        assert matcher.poll(1700) is None


def test_message_action_is_simulated():
    runner = ActionRunner()
    line = runner.run(Shortcut(
        name="Ping",
        pattern="--",
        max_gap_ms=800,
        max_span_ms=2000,
        action="message",
        message="all clear",
        destination="on-screen log",
    ), "venue")
    assert "MESSAGE" in line
    assert "911" not in line
    assert runner.active_alert() == "Ping"


def test_sos_log_says_simulated():
    runner = ActionRunner()
    line = runner.run(Shortcut(
        name="SOS",
        pattern="...",
        max_gap_ms=400,
        max_span_ms=1500,
        action="sos",
        message="Emergency assist requested",
        destination="Nearest police station (simulated)",
    ), "Hackathon venue")
    assert "SIMULATED SOS" in line
    assert "NOT A REAL 911 CALL" in line
    assert runner.active_alert() == "SIMULATED SOS"


def test_camera_recording_warns_when_the_pattern_exists():
    with tempfile.TemporaryDirectory() as folder:
        matcher = _matcher(Path(folder) / "shortcuts.json")
        matcher.start_recording()
        matcher.push(".", 0, 80)
        matcher.push(".", 200, 80)
        matcher.push(".", 400, 80)
        pattern, owner = matcher.finish_recording()
        assert pattern == "..."
        assert owner == "SOS"
        assert "already used by SOS" in matcher.active_notice()
        assert matcher.snapshot()["form_pattern"] == ""


def test_camera_recording_offers_a_new_pattern():
    with tempfile.TemporaryDirectory() as folder:
        matcher = _matcher(Path(folder) / "shortcuts.json")
        matcher.start_recording()
        matcher.push("-", 0, 400)
        matcher.push(".", 500, 80)
        pattern, owner = matcher.finish_recording()
        assert pattern == "-."
        assert owner == ""
        assert matcher.snapshot()["form_pattern"] == "-."
        assert matcher.take_form_pattern()["pattern"] == "-."
        assert matcher.snapshot()["form_pattern"] == ""


def test_used_pattern_belongs_to_the_other_shortcut():
    with tempfile.TemporaryDirectory() as folder:
        matcher = _matcher(Path(folder) / "shortcuts.json")
        assert pattern_owner(matcher.shortcuts, "...", "Help") == "SOS"
        assert pattern_owner(matcher.shortcuts, "...", "SOS") == ""
        assert pattern_owner(matcher.shortcuts, "-.-", "Help") == ""


if __name__ == "__main__":
    test_fast_three_dots_match_sos()
    test_slow_dots_do_not_match_sos()
    test_three_dashes_match_hello_world()
    test_longer_pattern_wins_after_pause()
    test_message_action_is_simulated()
    test_sos_log_says_simulated()
    test_camera_recording_warns_when_the_pattern_exists()
    test_camera_recording_offers_a_new_pattern()
    test_used_pattern_belongs_to_the_other_shortcut()
    print("shortcut tests passed")
