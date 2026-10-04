"""Hands-free eye-blink Morse code decoder.

Pipeline:
    camera -> FaceLandmarker (eye aspect ratio) -> blink/wink state machine
    -> shortcut matcher (Assist) or Morse decode
    -> text buffer + word prediction -> HUD (and optional OS typing).

Assist mode is the default. Three fast dots raise a simulated SOS alert.
The shortcut editor opens at http://127.0.0.1:8765

Run:
    python main.py                 # calibrate, then start in Assist mode
    python main.py --morse         # start in covert Morse mode
    python main.py --skip-calib    # reuse saved calibration (or defaults)
    python main.py --type          # also type confirmed words into focused app

Blink language:
    short blink (both eyes, 40-250 ms) .... dot
    longer blink (both eyes, over 250 ms) . dash
    pause (eyes open ~0.7s) ........ end of letter
    space key ...................... word break (no automatic space)
    m .............................. toggle Assist / Morse mode
    left wink ...................... backspace (Morse mode)
    right wink once ................ accept suggestion #1 (Morse mode)
    right wink twice ............... accept suggestion #2
    right wink 3 times ............. accept suggestion #3

Keys: q quit | o open customize | m mode | Enter send cleaned
      c recalibrate | r reference | t typing | backspace | space word break
The Customize button opens the shortcut page. In Morse mode, Send confirms
the cleaned sentence. Assist shortcuts are sent as written.
"""

from __future__ import annotations

import argparse
import platform
import threading
import time
import webbrowser
from typing import List, Optional

import cv2

import config
import hud
import morse
from calibration import run_calibration
from predictor import WordPredictor
from state_machine import BlinkStateMachine, Event
from actions import ActionRunner
from cleaner import clean_message
from shortcuts import Shortcut, ShortcutMatcher
from tracker import EyeTracker
from typer import Typer
from workspace import start_workspace

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
        self.right_picks = 0        # consecutive right winks waiting to choose
        self._right_deadline = 0.0
        self._clean_raw = None
        self._clean_text = ""

    # ---- display helpers ---------------------------------------------- #
    def display_text(self) -> str:
        return self.text + self.current_word

    def cleaned_preview(self) -> str:
        """Readable sentence for the current raw Morse text. Not sent yet."""
        raw = self.display_text().strip()
        if raw == self._clean_raw:
            return self._clean_text
        self._clean_raw = raw
        self._clean_text = clean_message(raw)
        return self._clean_text

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
            self.current_word = ""

    def backspace(self) -> None:
        if self.symbol_buffer:
            self.symbol_buffer = self.symbol_buffer[:-1]
            return
        if self.current_word:
            self.current_word = self.current_word[:-1]
            return
        if self.text:
            self.text = self.text[:-1]

    def note_right_wink(self, now_ms: float) -> None:
        """Count a right wink. 1, 2, or 3 picks suggestion #1, #2, or #3."""
        self.right_picks = min(self.right_picks + 1, config.NUM_SUGGESTIONS)
        self._right_deadline = now_ms + config.RIGHT_SELECT_GAP_MS
        self.flash(f"pick #{self.right_picks}", seconds=3.2)

    def cancel_right_picks(self) -> None:
        self.right_picks = 0
        self._right_deadline = 0.0

    def poll_right_picks(self, now_ms: float) -> None:
        """Apply the counted right winks once the pause has elapsed."""
        if self.right_picks and now_ms >= self._right_deadline:
            index = self.right_picks - 1
            suggestions = self.suggestions()
            self.cancel_right_picks()
            self.accept_suggestion(suggestions, index)

    def accept_suggestion(self, suggestions: List[str], index: int = 0) -> None:
        if not suggestions or index < 0 or index >= len(suggestions):
            self.flash("no suggestion")
            return
        word = suggestions[index]
        self.flash(word)
        self.text += word + " "
        self.current_word = ""
        self.symbol_buffer = ""
        self.cancel_right_picks()

    def suggestions(self) -> List[str]:
        return self.predictor.predict(self.current_word)


# --------------------------------------------------------------------------- #
def open_camera(index: int) -> cv2.VideoCapture:
    backend = cv2.CAP_DSHOW if platform.system() == "Windows" else 0
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    return cap


def handle_events(events, engine: TextEngine, now_ms: float, mode: str,
                  matcher: ShortcutMatcher, actions: ActionRunner,
                  blink_ms: float = 0.0) -> None:
    for ev in events:
        if ev is Event.DOT or ev is Event.DASH:
            symbol = "." if ev is Event.DOT else "-"
            _beep(900 if ev is Event.DOT else 600)
            # A both-eyes blink while choosing must not wipe the count.
            if mode == "morse" and engine.right_picks:
                continue
            if mode == "assist":
                matcher.push(symbol, now_ms, blink_ms)
            else:
                engine.cancel_right_picks()
                engine.add_symbol(symbol)
            continue
        if mode != "morse":
            continue
        if ev is Event.LETTER_GAP:
            engine.commit_letter()
        elif ev is Event.WINK_LEFT:
            engine.cancel_right_picks()
            engine.backspace()
            _beep(400)
        elif ev is Event.WINK_RIGHT:
            engine.note_right_wink(now_ms)
            _beep(900 + 150 * engine.right_picks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Eye-blink Morse decoder")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    parser.add_argument("--skip-calib", action="store_true",
                        help="reuse saved calibration.json or defaults")
    parser.add_argument("--no-save", action="store_true",
                        help="do not persist calibration results")
    parser.add_argument("--type", action="store_true",
                        help="type confirmed words into the focused app")
    parser.add_argument("--no-zoom", action="store_true",
                        help="disable zooming into the eye region for detection")
    parser.add_argument("--morse", action="store_true",
                        help="start in covert Morse mode instead of Assist mode")
    args = parser.parse_args()

    cap = open_camera(args.camera)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera index {args.camera}")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    tracker = EyeTracker(zoom=not args.no_zoom)

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
    matcher = ShortcutMatcher()
    actions = ActionRunner()
    start_workspace(matcher)
    mode = "morse" if args.morse else "assist"

    show_reference = False
    show_eyes = True
    fps = 0.0
    last = time.perf_counter()

    def send_cleaned() -> None:
        """Send the cleaned sentence. The raw blink text stays a preview until then."""
        if mode != "morse":
            engine.flash("switch to Morse to send")
            return
        engine.commit_word()
        raw = engine.display_text().strip()
        cleaned = clean_message(raw)
        if not cleaned:
            engine.flash("nothing to send")
            return
        actions.run(Shortcut(
            name="SENT",
            pattern="",
            max_gap_ms=0,
            max_span_ms=0,
            action="message",
            message=cleaned,
            destination="Cleaned Morse message",
        ), matcher.demo_location)
        if typer.enabled:
            typer.type_text(cleaned + " ")
        engine.text = ""
        engine.current_word = ""
        engine.symbol_buffer = ""
        engine.cancel_right_picks()

    def toggle_mode() -> None:
        nonlocal mode
        mode = "morse" if mode == "assist" else "assist"
        matcher.clear()
        engine.symbol_buffer = ""
        engine.cancel_right_picks()
        engine.flash("MORSE mode" if mode == "morse" else "ASSIST mode")

    def on_mouse(event, x, y, _flags, _param) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        fw, fh = hud.frame_size
        try:
            x0, y0, ww, hh = cv2.getWindowImageRect(WINDOW)
            if ww > 0 and hh > 0:
                x = int((x - x0) * fw / ww)
                y = int((y - y0) * fh / hh)
        except Exception:
            pass
        name = hud.hit_button(x, y)
        if name == "customize":
            webbrowser.open(f"http://127.0.0.1:{config.WORKSPACE_PORT}")
        elif name == "mode":
            toggle_mode()
        elif name == "send":
            send_cleaned()

    cv2.setMouseCallback(WINDOW, on_mouse)

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
            handle_events(events, engine, now_ms, mode, matcher, actions,
                          machine.last_blink_ms)
            if mode == "assist":
                hit = matcher.poll(now_ms)
                if hit is not None:
                    actions.run(hit, matcher.demo_location)
            if mode == "morse":
                engine.poll_right_picks(now_ms)
            # Recompute suggestions if the buffer changed this frame.
            suggestions = engine.suggestions()

            # Smooth FPS estimate.
            now = time.perf_counter()
            dt = now - last
            last = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)

            alert = actions.active_alert() or ""
            hud.draw_hud(frame, reading, machine.state, runtime, engine,
                         suggestions, show_reference, typer.enabled, fps,
                         show_eyes, tracker.zoom_enabled, mode,
                         alert, actions.alert_detail if alert else "",
                         matcher.pending_pattern())
            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("c"):
                new_rc = run_calibration(cap, tracker, WINDOW)
                if new_rc is not None:
                    runtime.close_thresh = new_rc.close_thresh
                    runtime.min_open_drop = new_rc.min_open_drop
                    runtime.open_mean = new_rc.open_mean
                    runtime.closed_mean = new_rc.closed_mean
                    runtime.close_thresh_left = new_rc.close_thresh_left
                    runtime.close_thresh_right = new_rc.close_thresh_right
                    if not args.no_save:
                        runtime.save()
            elif key == ord("o"):
                webbrowser.open(f"http://127.0.0.1:{config.WORKSPACE_PORT}")
            elif key == ord("m"):
                toggle_mode()
            elif key == ord("r"):
                show_reference = not show_reference
            elif key == ord("e"):
                show_eyes = not show_eyes
            elif key == ord("z"):
                on = tracker.toggle_zoom()
                engine.flash("eye zoom ON" if on else "eye zoom OFF")
            elif key in (ord("["), ord("-")):
                # Less sensitive to closing: eyes stay "open" at smaller openings.
                runtime.nudge(-0.01)
                engine.flash(f"thr {runtime.close_thresh:0.3f}")
                if not args.no_save:
                    runtime.save()
            elif key in (ord("]"), ord("=")):
                runtime.nudge(+0.01)
                engine.flash(f"thr {runtime.close_thresh:0.3f}")
                if not args.no_save:
                    runtime.save()
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
            elif key in (13, 10):  # Enter sends the cleaned sentence
                send_cleaned()
    finally:
        cap.release()
        tracker.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
