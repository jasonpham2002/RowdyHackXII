"""Demo actions for blink shortcuts.

SOS writes a simulated dispatch line and raises an on-screen alarm. It does
not call or text 911. A message action appends to the same log and, when the
destination is an http(s) URL, posts JSON there.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import List, Optional

import config
from shortcuts import Shortcut


class ActionRunner:
    def __init__(self) -> None:
        self.alert_until = 0.0
        self.alert_title = ""
        self.alert_detail = ""
        self.recent: List[str] = []

    def active_alert(self) -> Optional[str]:
        if time.time() < self.alert_until:
            return self.alert_title
        return None

    def run(self, shortcut: Shortcut, location: str) -> str:
        if shortcut.action == "sos":
            return self._sos(shortcut, location)
        return self._message(shortcut)

    def _remember(self, line: str) -> None:
        self.recent.append(line)
        self.recent = self.recent[-6:]
        with config.DISPATCH_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _sos(self, shortcut: Shortcut, location: str) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"{stamp} SIMULATED SOS | pattern={shortcut.pattern} | "
            f"destination={shortcut.destination or 'Nearest police station (simulated)'} | "
            f"location={location} | NOT A REAL 911 CALL"
        )
        self._remember(line)
        self.alert_until = time.time() + config.ASSIST_SHOW_S
        self.alert_title = "SIMULATED SOS"
        self.alert_detail = (
            "Not a real 911 call. "
            + (shortcut.destination or "Nearest police station (simulated)")
        )
        self._alarm()
        return line

    def _message(self, shortcut: Shortcut) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        text = shortcut.message or shortcut.name
        dest = shortcut.destination or "on-screen log"
        line = f"{stamp} MESSAGE | to={dest} | {text}"
        self._remember(line)
        self.alert_until = time.time() + config.ASSIST_SHOW_S
        self.alert_title = shortcut.name or "MESSAGE"
        self.alert_detail = text
        if dest.startswith("http://") or dest.startswith("https://"):
            self._post(dest, {
                "name": shortcut.name,
                "pattern": shortcut.pattern,
                "message": text,
                "simulated": True,
            })
        return line

    @staticmethod
    def _post(url: str, payload: dict) -> None:
        def run() -> None:
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url, data=data, headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=3).read()
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _alarm() -> None:
        def run() -> None:
            try:
                import winsound
                for freq in (880, 660, 880, 660, 880):
                    winsound.Beep(freq, 180)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()
