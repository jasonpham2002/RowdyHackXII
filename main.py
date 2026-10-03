"""Hands-free eye-blink Morse code decoder.

Pipeline:
    camera -> FaceMesh (EAR) -> blink/wink state machine -> Morse decode
    -> text buffer + word prediction -> HUD (and optional OS typing).

Run:
    python main.py                 # calibrate, then start decoding
    python main.py --skip-calib    # reuse saved calibration (or defaults)
    python main.py --type          # also type confirmed words into focused app

Blink language:
    short blink (both eyes) ........ dot
    long blink (both eyes) ......... dash
    pause (eyes open ~0.7s) ........ end of letter
    longer pause (~1.5s) ........... space (end of word)
    left wink ...................... backspace
    right wink ..................... accept suggestion #1

Keys: q quit | c recalibrate | r reference chart | t toggle typing
      backspace delete | space insert word break
"""

from __future__ import annotations

import argparse
import platform
import threading
import time
from typing import List, Optional

import cv2

import config
import hud
import morse
from calibration import run_calibration
from predictor import WordPredictor
from state_machine import BlinkStateMachine, Event
from tracker import EyeTracker
from typer import Typer

WINDOW = "Eye Morse Decoder"


# --------------------------------------------------------------------------- #
# Audio cue (non-blocking beep on Windows; silently ignored elsewhere).
# --------------------------------------------------------------------------- #
def _beep(freq: int) -> None:
    if not config.AUDIO_CUES or platform.system() != "Windows":
        return

    def run():
        try:
            import winsound

            winsound.Beep(freq, 80)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- #
# Text engine: owns the Morse buffer and the decoded text.
# --------------------------------------------------------------------------- #
class TextEngine:
    def __init__(self, predictor: WordPredictor, typer: Typer) -> None:
        self.predictor = predictor
        self.typer = typer
        self.symbol_buffer = ""     # dots/dashes of the letter being built
        self.text = ""              # finalized text (completed words + spaces)
        self.current_word = ""      # in-progress word, not yet in ``text``
        self._flash_msg = ""
        self._flash_until = 0.0

    # ---- display helpers ---------------------------------------------- #
    def display_text(self) -> str:
        return self.text + self.current_word

    def flash(self, msg: str, seconds: float = 0.8) -> None:
        self._flash_msg = msg
        self._flash_until = time.perf_counter() + seconds

    def active_flash(self) -> Optional[str]:
        if time.perf_counter() < self._flash_until:
            return self._flash_msg
        return None

    # ---- event handlers ----------------------------------------------- #
    def add_symbol(self, symbol: str) -> None:
        self.symbol_buffer += symbol

    def commit_letter(self) -> None:
        if not self.symbol_buffer:
            return
        char = morse.decode(self.symbol_buffer)
        if char is None:
            self.flash(f"? {self.symbol_buffer}")
        else:
            self.current_word += char
        self.symbol_buffer = ""

    def commit_word(self) -> None:
        # Finish any pending letter first.
        self.commit_letter()
        if self.current_word:
            self.text += self.current_word + " "
            self.typer.type_text(self.current_word + " ")
            self.current_word = ""

    def backspace(self) -> None:
        if self.symbol_buffer:
            self.symbol_buffer = self.symbol_buffer[:-1]
            return
        if self.current_word:
            self.current_word = self.current_word[:-1]
            self.typer.backspace()
            return
        if self.text:
            self.text = self.text[:-1]
            self.typer.backspace()

    def accept_suggestion(self, suggestions: List[str]) -> None:
        if not suggestions:
            return
        word = suggestions[0]
        completion = word[len(self.current_word):]
        self.typer.type_text(completion + " ")
        self.text += word + " "
        self.current_word = ""
        self.symbol_buffer = ""

    def suggestions(self) -> List[str]:
        return self.predictor.predict(self.current_word)


# --------------------------------------------------------------------------- #
def open_camera(index: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if platform.system() == "Windows" else 0
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    return cap


def handle_events(events, engine: TextEngine, suggestions: List[str]) -> None:
    for ev in events:
        if ev is Event.DOT:
            engine.add_symbol(".")
            _beep(900)
        elif ev is Event.DASH:
            engine.add_symbol("-")
            _beep(600)
        elif ev is Event.LETTER_GAP:
            engine.commit_letter()
        elif ev is Event.WORD_GAP:
            engine.commit_word()
        elif ev is Event.WINK_LEFT:
            engine.backspace()
            _beep(400)
        elif ev is Event.WINK_RIGHT:
            engine.accept_suggestion(suggestions)
            _beep(1100)


def main() -> None:
    parser = argparse.ArgumentParser(description="Eye-blink Morse decoder")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    parser.add_argument("--skip-calib", action="store_true",
                        help="reuse saved calibration.json or defaults")
    parser.add_argument("--no-save", action="store_true",
                        help="do not persist calibration results")
    parser.add_argument("--type", action="store_true",
                        help="type confirmed words into the focused app")
    args = parser.parse_args()

    cap = open_camera(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera index {args.camera}")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    tracker = EyeTracker()

    # ---- Calibration --------------------------------------------------- #
    runtime: Optional[config.RuntimeConfig] = None
    if args.skip_calib:
        runtime = config.RuntimeConfig.load()
    if runtime is None and not args.skip_calib:
        runtime = run_calibration(cap, tracker, WINDOW)
        if runtime is not None and not args.no_save:
            runtime.save()
    if runtime is None:
        runtime = config.RuntimeConfig()
        print(f"[calibration] using defaults close_thresh={runtime.close_thresh}")
    else:
        print(f"[calibration] close_thresh={runtime.close_thresh} "
              f"(open={runtime.open_mean}, closed={runtime.closed_mean})")

    machine = BlinkStateMachine(runtime)
    predictor = WordPredictor()
    typer = Typer(enabled=args.type)
    engine = TextEngine(predictor, typer)

    show_reference = False
    fps = 0.0
    last = time.perf_counter()

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if config.FLIP_HORIZONTAL:
                frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            now_ms = time.perf_counter() * 1000.0
            reading = tracker.process(rgb, now_ms)

            events = machine.update(reading, now_ms)
            suggestions = engine.suggestions()
            handle_events(events, engine, suggestions)
            # Recompute suggestions if the buffer changed this frame.
            suggestions = engine.suggestions()

            # Smooth FPS estimate.
            now = time.perf_counter()
            dt = now - last
            last = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)

            hud.draw_hud(frame, reading, machine.state, runtime, engine,
                         suggestions, show_reference, typer.enabled, fps)
            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("c"):
                new_rc = run_calibration(cap, tracker, WINDOW)
                if new_rc is not None:
                    runtime.close_thresh = new_rc.close_thresh
                    runtime.min_ear_drop = new_rc.min_ear_drop
                    runtime.open_mean = new_rc.open_mean
                    runtime.closed_mean = new_rc.closed_mean
                    if not args.no_save:
                        runtime.save()
            elif key == ord("r"):
                show_reference = not show_reference
            elif key == ord("t"):
                state = typer.toggle()
                if not typer.available:
                    engine.flash("pynput not available")
                else:
                    engine.flash("typing ON" if state else "typing OFF")
            elif key == 8:  # backspace
                engine.backspace()
            elif key == 32:  # space
                engine.commit_word()
    finally:
        cap.release()
        tracker.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
