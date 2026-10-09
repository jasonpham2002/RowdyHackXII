"""Hands-free eye-blink Morse code decoder.

Pipeline:
    camera -> FaceLandmarker (eye aspect ratio) -> blink/wink state machine
    -> shortcut matcher (Assist) or Morse decode
    -> text buffer + word prediction -> HUD (and optional OS typing).

Assist mode is the default. Three fast dots raise a simulated SOS alert.
The shortcut editor opens at http://127.0.0.1:8765

Trusted Text Room:
    python main.py opens the room page. Host a room or join another laptop
    there. Send publishes only the confirmed line. Webcam frames, landmarks,
    blink events, calibration values, and unfinished Morse drafts stay local.

Run:
    python main.py
    python main.py --morse
    python main.py --morse --room ROWDY1 --sender-name "Gail"  # optional overrides
    python main.py --skip-calib
    python main.py --type

Blink language:
    short blink (both eyes, 40-250 ms) .... dot
    longer blink (both eyes, over 250 ms) . dash
    pause (eyes open ~0.7s) .............. end of letter
    space key ............................ word break (no automatic space)
    m .................................... toggle Assist / Morse mode
    left wink, then right wink ........... send the line (Morse mode)
    left wink alone ...................... backspace, after a short wait (Morse mode)
    right wink once ...................... keep the raw line
    right wink twice ..................... accept autocorrect, or suggestion #2
    right wink 3 times ................... suggestion #3

Keys:
    q quit | o open customize | m mode | Enter send
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
import queue
import webbrowser
from typing import List, Optional

import cv2

import config
import hud
import morse
from actions import ActionRunner
from calibration import run_calibration
from chat_client import fetch_messages, load_session, publish_confirmed_message
from cleaner import clean_message
from predictor import WordPredictor
from shortcuts import Shortcut, ShortcutMatcher
from state_machine import BlinkStateMachine, Event
from tracker import EyeTracker
from typer import Typer
from workspace import start_workspace


WINDOW = "Eye Morse Decoder"


def _scale_click(
    x: int,
    y: int,
    src_w: int,
    src_h: int,
    frame_w: int,
    frame_h: int,
) -> tuple[int, int]:
    """Scale a point from a window rectangle onto the camera image."""
    if src_w <= 0 or src_h <= 0:
        return x, y

    return int(x * frame_w / src_w), int(y * frame_h / src_h)


def _click_to_frame(
    x: int,
    y: int,
    frame_w: int,
    frame_h: int,
) -> tuple[int, int]:
    """Map a click onto the camera image."""
    mapped = _cursor_in_image(frame_w, frame_h)

    if mapped is not None:
        return mapped

    return x, y


def _cursor_in_image(frame_w: int, frame_h: int) -> Optional[tuple[int, int]]:
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

        return _scale_click(
            int(point.x),
            int(point.y),
            int(rect.right - rect.left),
            int(rect.bottom - rect.top),
            frame_w,
            frame_h,
        )

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
# Audio cue.
# --------------------------------------------------------------------------- #
def _beep(freq: int) -> None:
    if not config.AUDIO_CUES or platform.system() != "Windows":
        return

    def run() -> None:
        try:
            import winsound

            winsound.Beep(freq, 80)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- #
# Text engine.
# --------------------------------------------------------------------------- #
class TextEngine:
    def __init__(self, predictor: WordPredictor, typer: Typer) -> None:
        self.predictor = predictor
        self.typer = typer
        self.symbol_buffer = ""
        self.text = ""
        self.current_word = ""
        self._flash_msg = ""
        self._flash_until = 0.0
        self.right_picks = 0
        self._right_deadline = 0.0
        self._send_arm_until = 0.0
        self._clean_raw: Optional[str] = None
        self._clean_text = ""

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
        self.commit_letter()

        if self.current_word:
            self.text += self.current_word + " "
            self.current_word = ""

    def arm_send_gesture(self, now_ms: float) -> None:
        """A left wink may start a send. A right wink must follow before it deletes."""
        self._send_arm_until = now_ms + config.SEND_GESTURE_MS
        self.flash("right wink sends", seconds=1.8)

    def confirm_send_gesture(self, now_ms: float) -> bool:
        """Return True when a right wink arrived in time to send."""
        if self._send_arm_until and now_ms <= self._send_arm_until:
            self._send_arm_until = 0.0
            return True
        return False

    def expire_send_gesture(self, now_ms: float) -> bool:
        """A left wink with no following right wink becomes a backspace."""
        if self._send_arm_until and now_ms > self._send_arm_until:
            self.backspace()
            return True
        return False

    def backspace(self) -> None:
        self._send_arm_until = 0.0
        if self.symbol_buffer:
            self.symbol_buffer = self.symbol_buffer[:-1]
            return

        if self.current_word:
            self.current_word = self.current_word[:-1]
            return

        if self.text:
            self.text = self.text[:-1]

    def _pending_correction(self) -> str:
        """Return cleaned text only when it differs from the raw Morse line."""
        raw = self.display_text().strip()

        if not raw:
            return ""

        clean = self.cleaned_preview().strip()

        if not clean or clean.upper() == raw.upper():
            return ""

        return clean

    def choice_options(self) -> List[tuple[str, str]]:
        """Return up to three explicit right-wink choices."""
        raw = self.display_text().strip()
        words = self.predictor.predict(self.current_word) if raw else []
        clean = self._pending_correction()

        if not words and not clean:
            return []

        rows: List[tuple[str, str]] = [("raw", raw)]

        if clean:
            rows.append(("clean", clean))

        for word in words:
            if len(rows) >= config.NUM_SUGGESTIONS:
                break

            rows.append(("word", word))

        return rows

    def note_right_wink(self, now_ms: float) -> None:
        """Count a right wink. Each wink advances to the next choice."""
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
        """Apply queued right-wink choice after the selection pause."""
        if self.right_picks and now_ms >= self._right_deadline:
            index = self.right_picks - 1
            options = self.choice_options()
            self.cancel_right_picks()
            self.apply_choice(options, index)

    def apply_choice(
        self,
        options: List[tuple[str, str]],
        index: int,
    ) -> None:
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
# Camera.
# --------------------------------------------------------------------------- #
class ThreadedCamera:
    """Continuously reads frames in a background thread to prevent buffer lag on macOS."""
    def __init__(self, index: int = 0):
        system = platform.system()
        if system == "Windows":
            backend = cv2.CAP_DSHOW
        elif system == "Darwin":
            backend = cv2.CAP_AVFOUNDATION
        else:
            backend = 0
            
        self.cap = cv2.VideoCapture(index, backend)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        self.ret, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.new_frame = False
        
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                if ret:
                    self.frame = frame
                self.new_frame = True
                self.condition.notify_all()
            if not ret:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            while self.running and not self.new_frame:
                if not self.condition.wait(timeout=1.0):
                    break
            self.new_frame = False
            return self.ret, (self.frame.copy() if self.frame is not None else None)

    def release(self):
        self.running = False
        with self.lock:
            self.condition.notify_all()
        self.thread.join(timeout=1.0)
        self.cap.release()

    def isOpened(self):
        return self.cap.isOpened()


# --------------------------------------------------------------------------- #
# Event handling.
# --------------------------------------------------------------------------- #
def handle_events(
    events,
    engine: TextEngine,
    now_ms: float,
    mode: str,
    matcher: ShortcutMatcher,
    actions: ActionRunner,
    blink_ms: float = 0.0,
    on_send=None,
) -> None:
    for event in events:
        if event is Event.DOT or event is Event.DASH:
            symbol = "." if event is Event.DOT else "-"
            _beep(900 if event is Event.DOT else 600)

            if mode == "morse" and engine.right_picks:
                continue

            if mode == "assist":
                matcher.push(symbol, now_ms, blink_ms)
            else:
                if engine._send_arm_until:
                    engine.backspace()
                engine.cancel_right_picks()
                engine.add_symbol(symbol)

            continue

        if mode != "morse":
            continue

        if event is Event.LETTER_GAP:
            engine.commit_letter()

        elif event is Event.WINK_LEFT:
            engine.cancel_right_picks()
            engine.arm_send_gesture(now_ms)
            _beep(400)

        elif event is Event.WINK_RIGHT:
            if engine.confirm_send_gesture(now_ms):
                if on_send is not None:
                    on_send()
                _beep(1200)
            else:
                engine.note_right_wink(now_ms)
                _beep(900 + 150 * engine.right_picks)


# --------------------------------------------------------------------------- #
# Main.
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Eye-blink Morse decoder")

    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX)

    parser.add_argument(
        "--skip-calib",
        action="store_true",
        help="Reuse saved calibration.json or defaults.",
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist calibration results.",
    )

    parser.add_argument(
        "--type",
        action="store_true",
        help="Type confirmed messages into the focused application.",
    )

    parser.add_argument(
        "--no-zoom",
        action="store_true",
        help="Disable zooming into the eye region for detection.",
    )

    parser.add_argument(
        "--morse",
        action="store_true",
        help="Start in Morse mode instead of Assist mode.",
    )

    parser.add_argument(
        "--room",
        default=None,
        help="Override the room code saved on the setup page.",
    )

    parser.add_argument(
        "--room-server",
        default=None,
        help="Override the room server saved on the setup page.",
    )

    parser.add_argument(
        "--sender-name",
        default=None,
        help="Override the name saved on the setup page.",
    )

    args = parser.parse_args()

    def active_room() -> dict:
        session = load_session()
        if args.room:
            session["room"] = "".join(
                char for char in args.room.upper() if char.isalnum()
            )[:12] or session["room"]
        if args.sender_name:
            session["name"] = args.sender_name.strip()[:40] or session["name"]
        if args.room_server:
            session["server_url"] = args.room_server.strip().rstrip("/")
        return session

    def start_room_server() -> None:
        def run() -> None:
            try:
                from chat_server import run_server
                run_server("0.0.0.0", config.ROOM_PORT)
            except Exception as exc:
                print(f"[room] server not started: {exc}")

        threading.Thread(target=run, daemon=True).start()

    start_room_server()
    joined = active_room()
    print(
        f"[room] {joined['name']} in {joined['room']} via {joined['server_url']}"
    )

    cap = ThreadedCamera(args.camera)

    if not cap.isOpened():
        raise SystemExit(f"Could not open camera index {args.camera}")

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    tracker = EyeTracker(zoom=not args.no_zoom)

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
        print(
            f"[calibration] close_thresh={runtime.close_thresh} "
            f"(open={runtime.open_mean}, closed={runtime.closed_mean})"
        )

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
    room_label = ""
    room_queue = queue.Queue()

    def poll_room():
        seen_ids = set()
        primed = False
        while True:
            try:
                info = active_room()
                incoming, err = fetch_messages(
                    info["room"],
                    info["server_url"],
                    token=str(info.get("token", "")),
                )
                msgs = []
                if not err:
                    for item in incoming:
                        mid = str(item.get("id", ""))
                        if not mid or mid in seen_ids:
                            continue
                        seen_ids.add(mid)
                        sender = str(item.get("sender", ""))
                        text = str(item.get("text", "")).strip()
                        if primed and sender != info["name"] and text:
                            msgs.append(f"{sender}: {text[:80]}")
                    primed = True
                label = f"Room {info['room']} · {info['name']}"
                if err:
                    label = f"Room {info['room']} · {err[:60]}"
                room_queue.put((label, msgs))
            except Exception:
                pass
            time.sleep(1.0)

    threading.Thread(target=poll_room, daemon=True).start()

    def send_confirmed_message() -> None:
        """Send only text visible on screen after explicit user confirmation."""
        if mode != "morse":
            engine.flash("switch to Morse to send")
            return

        engine.commit_word()

        raw = engine.display_text().strip()
        message = engine.cleaned_preview()

        if not message:
            engine.flash("nothing to send")
            return

        actions.run(
            Shortcut(
                name="SENT",
                pattern="",
                max_gap_ms=0,
                max_span_ms=0,
                action="message",
                message=message,
                destination="Morse message",
            ),
            matcher.demo_location,
        )

        joined = active_room()
        delivered, error = publish_confirmed_message(
            text=message,
            room=joined["room"],
            sender=joined["name"],
            server_url=joined["server_url"],
            token=str(joined.get("token", "")),
        )

        if delivered:
            engine.flash(f"sent to room {joined['room']}", seconds=1.8)
        else:
            engine.flash(f"local send only: {error}", seconds=2.8)

        if typer.enabled:
            typer.type_text(message + " ")

        engine.text = ""
        engine.current_word = ""
        engine.symbol_buffer = ""
        engine.cancel_right_picks()
        engine._clean_raw = None
        engine._clean_text = ""

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
        engine._send_arm_until = 0.0
        engine.flash("MORSE mode" if mode == "morse" else "ASSIST mode")

    def on_mouse(event, x, y, _flags, _param) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return

        frame_width, frame_height = hud.frame_size
        x, y = _click_to_frame(x, y, frame_width, frame_height)
        name = hud.hit_button(x, y)

        if name == "customize":
            webbrowser.open(
                f"http://127.0.0.1:{config.WORKSPACE_PORT}"
            )

        elif name == "mode":
            toggle_mode()

        elif name == "send":
            send_confirmed_message()

        elif name == "record":
            toggle_record()

        elif name == "room":
            webbrowser.open(f"http://127.0.0.1:{config.ROOM_PORT}/")
            engine.flash("room page opened", seconds=2)

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

            handle_events(
                events,
                engine,
                now_ms,
                mode,
                matcher,
                actions,
                machine.last_blink_ms,
                send_confirmed_message,
            )

            if mode == "morse":
                engine.expire_send_gesture(now_ms)

            if mode == "assist":
                hit = matcher.poll(now_ms)

                if hit is not None:
                    actions.run(hit, matcher.demo_location)

            if mode == "morse":
                engine.poll_right_picks(now_ms)

            suggestions = engine.suggestions() if mode == "morse" else []

            now = time.perf_counter()
            dt = now - last
            last = now

            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)

            try:
                while True:
                    rl, msgs = room_queue.get_nowait()
                    room_label = rl
                    for msg in msgs:
                        engine.flash(msg, seconds=5)
            except queue.Empty:
                pass

            alert = actions.active_alert() or ""

            hud.draw_hud(
                frame,
                reading,
                machine.state,
                runtime,
                engine,
                suggestions,
                show_reference,
                typer.enabled,
                fps,
                show_eyes,
                tracker.zoom_enabled,
                mode,
                alert,
                actions.alert_detail if alert else "",
                matcher.pending_pattern(),
                matcher.is_recording(),
                matcher.active_notice(),
                room_label,
            )

            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):
                break

            elif key == ord("c"):
                new_runtime = run_calibration(cap, tracker, WINDOW)

                if new_runtime is not None:
                    runtime.close_thresh = new_runtime.close_thresh
                    runtime.min_open_drop = new_runtime.min_open_drop
                    runtime.open_mean = new_runtime.open_mean
                    runtime.closed_mean = new_runtime.closed_mean
                    runtime.close_thresh_left = new_runtime.close_thresh_left
                    runtime.close_thresh_right = new_runtime.close_thresh_right

                    if not args.no_save:
                        runtime.save()

            elif key == ord("o"):
                webbrowser.open(
                    f"http://127.0.0.1:{config.WORKSPACE_PORT}"
                )

            elif key == ord("m"):
                toggle_mode()

            elif key == ord("r"):
                show_reference = not show_reference

            elif key == ord("e"):
                show_eyes = not show_eyes

            elif key == ord("z"):
                enabled = tracker.toggle_zoom()
                engine.flash("eye zoom ON" if enabled else "eye zoom OFF")

            elif key in (ord("["), ord("-")):
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
                enabled = typer.toggle()

                if not typer.available:
                    engine.flash("pynput not available")
                else:
                    engine.flash("typing ON" if enabled else "typing OFF")

            elif key == 8:
                engine.backspace()

            elif key == 32:
                engine.commit_word()

            elif key in (13, 10):
                send_confirmed_message()

    finally:
        cap.release()
        tracker.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()