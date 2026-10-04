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
    right wink once ................ keep the raw line
    right wink twice ............... accept autocorrect, or suggestion #2
    right wink 3 times ............. suggestion #3

Keys: q quit | o open customize | m mode | Enter send
      c recalibrate | r reference | t typing | backspace | space word break
The Customize button opens the shortcut page. Morse shows the raw line.
Autocorrect is a right-wink choice and is not applied until you pick it.
Send sends the line on screen. Assist shortcuts are sent as written.
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


def _scale_click(x: int, y: int, src_w: int, src_h: int,
                 frame_w: int, frame_h: int) -> tuple:
    """Scale a point from a window rectangle onto the camera image."""
    if src_w <= 0 or src_h <= 0:
        return x, y
    return int(x * frame_w / src_w), int(y * frame_h / src_h)


def _click_to_frame(x: int, y: int, frame_w: int, frame_h: int) -> tuple:
    """Map a click onto the camera image.

    OpenCV already turns a resized-window click into image pixels. Scaling
    those pixels by the outer window size again lands above the buttons.
    The cursor is read once, in the image child window, and scaled once.
    """
    mapped = _cursor_in_image(frame_w, frame_h)
    if mapped is not None:
        return mapped
    return x, y


def _cursor_in_image(frame_w: int, frame_h: int):
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        frame_hwnd = user32.FindWindowW(None, WINDOW)
        if not frame_hwnd:
            return None
        image_hwnd = _largest_child(user32, frame_hwnd)
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            return None
        if not user32.ScreenToClient(image_hwnd, ctypes.byref(point)):
            return None
        rect = wintypes.RECT()
        if not user32.GetClientRect(image_hwnd, ctypes.byref(rect)):
            return None
        return _scale_click(int(point.x), int(point.y),
                            int(rect.right - rect.left),
                            int(rect.bottom - rect.top),
                            frame_w, frame_h)
    except Exception:
        return None


def _largest_child(user32, parent):
    """OpenCV draws the camera in a child window inside the titled frame."""
    import ctypes
    from ctypes import wintypes

    best = parent
    best_area = 0
    child = user32.FindWindowExW(parent, None, None, None)
    while child:
        rect = wintypes.RECT()
        if user32.GetClientRect(child, ctypes.byref(rect)):
            area = max(0, int(rect.right)) * max(0, int(rect.bottom))
            if area > best_area:
                best_area = area
                best = child
        child = user32.FindWindowExW(parent, child, None, None)
    return best


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

    def _pending_correction(self) -> str:
        """Cleaned sentence when it differs from the raw line. Empty otherwise."""
        raw = self.display_text().strip()
        if not raw:
            return ""
        clean = self.cleaned_preview().strip()
        if not clean or clean.upper() == raw.upper():
            return ""
        return clean

    def choice_options(self) -> List[tuple]:
        """Up to 3 choices. Autocorrect is offered, never applied by itself."""
        raw = self.display_text().strip()
        words = self.predictor.predict(self.current_word) if raw else []
        clean = self._pending_correction()
        if not words and not clean:
            return []
        rows = [("raw", raw)]
        if clean:
            rows.append(("clean", clean))
        for word in words:
            if len(rows) >= config.NUM_SUGGESTIONS:
                break
            rows.append(("word", word))
        return rows

    def note_right_wink(self, now_ms: float) -> None:
        """Count a right wink. Each wink moves to the next choice."""
        options = self.choice_options()
        if not options:
            return
        self.right_picks = min(self.right_picks + 1, len(options))
        self._right_deadline = now_ms + config.RIGHT_SELECT_GAP_MS
        self.flash(f"pick #{self.right_picks}", seconds=3.2)

    def cancel_right_picks(self) -> None:
        self.right_picks = 0
        self._right_deadline = 0.0

    def poll_right_picks(self, now_ms: float) -> None:
        """Apply the counted right winks once the pause has elapsed."""
        if self.right_picks and now_ms >= self._right_deadline:
            index = self.right_picks - 1
            options = self.choice_options()
            self.cancel_right_picks()
            self.apply_choice(options, index)

    def apply_choice(self, options: List[tuple], index: int) -> None:
        if not options or index < 0 or index >= len(options):
            self.flash("no suggestion")
            return
        kind, label = options[index]
        if kind == "raw":
            self.flash(label)
            return
        if kind == "clean":
            self.text = label + " "
            self.current_word = ""
            self.symbol_buffer = ""
            self._clean_raw = None
            self.flash(label)
            return
        self.flash(label)
        self.text += label + " "
        self.current_word = ""
        self.symbol_buffer = ""

    def suggestions(self) -> List[str]:
        return [label for _kind, label in self.choice_options()]


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
        """Send the line on screen. Autocorrect is included only if it was chosen."""
        if mode != "morse":
            engine.flash("switch to Morse to send")
            return
        engine.commit_word()
        message = engine.display_text().strip()
        if not message:
            engine.flash("nothing to send")
            return
        actions.run(Shortcut(
            name="SENT",
            pattern="",
            max_gap_ms=0,
            max_span_ms=0,
            action="message",
            message=message,
            destination="Morse message",
        ), matcher.demo_location)
        if typer.enabled:
            typer.type_text(message + " ")
        engine.text = ""
        engine.current_word = ""
        engine.symbol_buffer = ""
        engine.cancel_right_picks()

    def toggle_record() -> None:
        if mode != "assist":
            engine.flash("switch to Assist to record", seconds=3)
            return
        if matcher.is_recording():
            pattern, owner = matcher.finish_recording()
            if not pattern:
                engine.flash("no blinks recorded", seconds=3)
            elif owner:
                engine.flash(matcher.active_notice(), seconds=5)
            else:
                engine.flash(pattern, seconds=3)
            return
        matcher.start_recording()
        engine.flash("recording blinks", seconds=2)

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
        x, y = _click_to_frame(x, y, fw, fh)
        name = hud.hit_button(x, y)
        if name == "customize":
            webbrowser.open(f"http://127.0.0.1:{config.WORKSPACE_PORT}")
        elif name == "mode":
            toggle_mode()
        elif name == "send":
            send_cleaned()
        elif name == "record":
            toggle_record()

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
            handle_events(events, engine, now_ms, mode, matcher, actions,
                          machine.last_blink_ms)
            if mode == "assist":
                hit = matcher.poll(now_ms)
                if hit is not None:
                    actions.run(hit, matcher.demo_location)
            if mode == "morse":
                engine.poll_right_picks(now_ms)
            suggestions = engine.suggestions() if mode == "morse" else []

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
                         matcher.pending_pattern(),
                         matcher.is_recording(),
                         matcher.active_notice())
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
