"""User-defined blink shortcuts.

A shortcut matches the most recent dots and dashes when two things are true:
the symbols equal the saved pattern, and the blinks landed inside that
pattern's time window. Matching happens on the blink stream itself, so three
fast dots can mean SOS without also becoming the Morse letter S.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from typing import List, Optional

import config


@dataclass
class Shortcut:
    name: str
    pattern: str
    max_gap_ms: float
    max_span_ms: float
    action: str
    message: str = ""
    destination: str = ""

    def clean_pattern(self) -> str:
        return "".join(ch for ch in self.pattern if ch in ".-")


class ShortcutMatcher:
    def __init__(self, path=config.SHORTCUTS_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.shortcuts: List[Shortcut] = []
        self.demo_location = "Hackathon venue (simulated)"
        self._mtime = 0.0
        # Each blink is (end_ms, duration_ms, symbol). Gap checks use the
        # eyes-open pause, so a long dash does not consume the gap budget.
        self.blinks: List[tuple[float, float, str]] = []
        self.recording = False
        self.recorded: List[tuple[float, str]] = []
        self._commit_at: Optional[float] = None
        self.reload(force=True)

    def reload(self, force: bool = False) -> None:
        if not self.path.exists():
            self._write_default()
        mtime = self.path.stat().st_mtime
        if not force and mtime == self._mtime:
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        rows = []
        for raw in data.get("shortcuts", []):
            pattern = "".join(ch for ch in str(raw.get("pattern", "")) if ch in ".-")
            if not pattern:
                continue
            rows.append(Shortcut(
                name=str(raw.get("name", pattern)),
                pattern=pattern,
                max_gap_ms=float(raw.get("max_gap_ms", config.SOS_MAX_GAP_MS)),
                max_span_ms=float(raw.get("max_span_ms", config.SOS_MAX_SPAN_MS)),
                action=str(raw.get("action", "message")),
                message=str(raw.get("message", "")),
                destination=str(raw.get("destination", "")),
            ))
        with self._lock:
            self.shortcuts = rows
            self.demo_location = str(data.get("demo_location", self.demo_location))
            self._mtime = mtime

    def save(self, shortcuts: List[Shortcut], demo_location: Optional[str] = None) -> None:
        payload = {
            "demo_location": demo_location or self.demo_location,
            "shortcuts": [asdict(sc) for sc in shortcuts],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.reload(force=True)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "demo_location": self.demo_location,
                "recording": self.recording,
                "recorded_pattern": "".join(sym for _, sym in self.recorded),
                "shortcuts": [asdict(sc) for sc in self.shortcuts],
            }

    def pending_pattern(self) -> str:
        with self._lock:
            return "".join(sym for _, _, sym in self.blinks)

    def clear(self) -> None:
        with self._lock:
            self.blinks.clear()
            self._commit_at = None

    def start_recording(self) -> None:
        with self._lock:
            self.recording = True
            self.recorded = []
            self.blinks = []
            self._commit_at = None

    def stop_recording(self) -> str:
        with self._lock:
            self.recording = False
            pattern = "".join(sym for _, sym in self.recorded)
            return pattern

    def push(self, symbol: str, now_ms: float, duration_ms: float = 0.0) -> Optional[Shortcut]:
        """Record one blink. Matching waits until ``poll`` sees a 1s pause.

        ``now_ms`` is when the eyes opened again. ``duration_ms`` is how long
        they stayed closed. The gap limit is the open pause between blinks.
        """
        self.reload()
        with self._lock:
            duration_ms = max(0.0, duration_ms)
            self.blinks.append((now_ms, duration_ms, symbol))
            if self.recording:
                self.recorded.append((now_ms, symbol))
                self.blinks = self.blinks[-12:]
                self._commit_at = None
                return None
            self._trim_locked(now_ms)
            self._commit_at = now_ms + config.SHORTCUT_HOLD_MS
            return None

    def poll(self, now_ms: float) -> Optional[Shortcut]:
        """After a 1s pause, fire the longest pattern that fits. One message."""
        self.reload()
        with self._lock:
            if self.recording or self._commit_at is None or now_ms < self._commit_at:
                return None
            self._commit_at = None
            self._trim_locked(now_ms)
            hit = self._match_locked()
            if hit is not None:
                self.blinks.clear()
            return hit

    def _trim_locked(self, now_ms: float) -> None:
        horizon = 4000.0
        if self.shortcuts:
            horizon = max(sc.max_span_ms for sc in self.shortcuts) + 200.0
        self.blinks = [
            (end, dur, sym)
            for end, dur, sym in self.blinks
            if now_ms - end <= horizon
        ]

    def _match_locked(self) -> Optional[Shortcut]:
        best: Optional[Shortcut] = None
        for sc in self.shortcuts:
            n = len(sc.pattern)
            if n == 0 or len(self.blinks) < n:
                continue
            window = self.blinks[-n:]
            symbols = "".join(sym for _, _, sym in window)
            if symbols != sc.pattern:
                continue
            ends = [end for end, _, _ in window]
            starts = [end - dur for end, dur, _ in window]
            if ends[-1] - starts[0] > sc.max_span_ms:
                continue
            gaps = [starts[i] - ends[i - 1] for i in range(1, n)]
            if any(gap > sc.max_gap_ms for gap in gaps):
                continue
            if best is None or n > len(best.pattern):
                best = sc
        return best

    def _write_default(self) -> None:
        default = Shortcut(
            name="SOS",
            pattern="...",
            max_gap_ms=config.SOS_MAX_GAP_MS,
            max_span_ms=config.SOS_MAX_SPAN_MS,
            action="sos",
            message="Emergency assist requested",
            destination="Nearest police station (simulated)",
        )
        payload = {
            "demo_location": "Hackathon venue (simulated)",
            "shortcuts": [asdict(default)],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
