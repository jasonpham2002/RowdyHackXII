"""Optional OS-level keyboard output (stretch goal).

When enabled, confirmed words are typed into whatever application currently has
focus using ``pynput``. If ``pynput`` is not installed the typer degrades to a
no-op and reports ``available == False`` so the rest of the app keeps working.
"""

from __future__ import annotations


class Typer:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.available = False
        self._kb = None
        try:
            from pynput.keyboard import Controller

            self._kb = Controller()
            self.available = True
        except Exception:
            self.available = False
            self.enabled = False

    def toggle(self) -> bool:
        if self.available:
            self.enabled = not self.enabled
        return self.enabled

    def type_text(self, text: str) -> None:
        if self.enabled and self._kb is not None and text:
            self._kb.type(text)

    def backspace(self) -> None:
        if self.enabled and self._kb is not None:
            from pynput.keyboard import Key

            self._kb.press(Key.backspace)
            self._kb.release(Key.backspace)
