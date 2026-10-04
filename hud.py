"""On-screen overlay (HUD) drawn on top of the camera feed with OpenCV."""

from __future__ import annotations

from typing import List

import cv2
import numpy as np

import config
import morse


FONT = cv2.FONT_HERSHEY_SIMPLEX

WHITE = (255, 255, 255)
GREEN = (0, 230, 0)
RED = (0, 0, 255)
YELLOW = (0, 230, 230)
CYAN = (230, 230, 0)
GREY = (170, 170, 170)
PANEL = (25, 25, 25)
BUTTON = (40, 90, 160)
BUTTON_ALT = (90, 70, 30)

# Click targets filled by draw_hud. Each item is (name, x1, y1, x2, y2).
buttons: list = []
frame_size = (1280, 720)


def hit_button(x: int, y: int) -> str:
    # A few pixels outside the painted rectangle still count as that button.
    pad_x, pad_y = 6, 18
    for name, x1, y1, x2, y2 in buttons:
        if x1 - pad_x <= x <= x2 + pad_x and y1 - pad_y <= y <= y2 + pad_y:
            return name
    return ""


def _button(frame, name, x, y, w, h, label, fill) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), fill, -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), WHITE, 2)
    _text(frame, label, (x + 18, y + h // 2 + 10), WHITE, 0.85, 2)
    buttons.append((name, x, y, x + w, y + h))


def _text(frame, s, org, color=WHITE, scale=0.7, thick=2):
    cv2.putText(
        frame,
        s,
        org,
        FONT,
        scale,
        (0, 0, 0),
        thick + 3,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame,
        s,
        org,
        FONT,
        scale,
        color,
        thick,
        cv2.LINE_AA,
    )


def _panel(frame, x1, y1, x2, y2, alpha=0.55):

    sub = frame[y1:y2, x1:x2]

    if sub.size == 0:
        return

    overlay = np.full_like(
        sub,
        PANEL,
    )

    frame[y1:y2, x1:x2] = cv2.addWeighted(
        overlay,
        alpha,
        sub,
        1 - alpha,
        0,
    )


def _draw_eyes(frame, reading, runtime):

    for ring, closed in (
        (
            reading.left_ring,
            reading.open_left
            < runtime.close_thresh_left,
        ),
        (
            reading.right_ring,
            reading.open_right
            < runtime.close_thresh_right,
        ),
    ):

        if not ring:
            continue

        pts = np.array(
            ring,
            dtype=np.int32,
        )

        cv2.polylines(
            frame,
            [pts],
            True,
            RED if closed else GREEN,
            2,
            cv2.LINE_AA,
        )


def _draw_openness_bar(
    frame,
    reading,
    runtime,
):
    """Open/close meter above the buttons, with the close line marked."""

    x = 500
    y = frame.shape[0] - 168

    w = 420
    h = 28

    closed = (
        reading.open_avg
        < runtime.close_thresh
    )
    _text(
        frame,
        "CLOSED" if closed else "OPEN",
        (x, y - 12),
        RED if closed else GREEN,
        0.7,
        2,
    )
    _text(
        frame,
        f"{reading.open_avg:0.3f}",
        (x + 150, y - 12),
        WHITE,
        0.7,
        2,
    )

    cv2.rectangle(
        frame,
        (x, y),
        (x + w, y + h),
        GREY,
        1,
    )

    max_v = max(
        0.45,
        runtime.open_mean * 1.4,
        runtime.close_thresh * 1.6,
    )

    val = (
        min(
            reading.open_avg,
            max_v,
        )
        / max_v
    )

    fill = int(
        w * val
    )

    cv2.rectangle(
        frame,
        (x, y),
        (
            x + fill,
            y + h,
        ),
        RED if closed else GREEN,
        -1,
    )

    tx = (
        x
        + int(
            w
            * min(
                runtime.close_thresh,
                max_v,
            )
            / max_v
        )
    )

    cv2.line(
        frame,
        (tx, y - 4),
        (
            tx,
            y + h + 4,
        ),
        YELLOW,
        2,
    )



def _symbols_pretty(
    symbols: str,
) -> str:

    return "".join(
        "DOT "
        if c == "."
        else "DASH "
        for c in symbols
    ).strip()


def _make_eye_inset(
    frame,
    reading,
    pad_ratio=0.6,
    target_w=300,
    max_h=150,
):

    pts = (
        list(reading.left_ring)
        + list(reading.right_ring)
    )

    if not pts:
        return None

    xs = [
        p[0]
        for p in pts
    ]

    ys = [
        p[1]
        for p in pts
    ]

    x1 = min(xs)
    x2 = max(xs)

    y1 = min(ys)
    y2 = max(ys)

    bw = x2 - x1
    bh = y2 - y1

    if bw <= 0 or bh <= 0:
        return None

    px = int(
        bw * pad_ratio
    )

    py = int(
        bh * (
            pad_ratio + 0.6
        )
    )

    h, w = frame.shape[:2]

    x1 = max(
        0,
        x1 - px,
    )

    y1 = max(
        0,
        y1 - py,
    )

    x2 = min(
        w,
        x2 + px,
    )

    y2 = min(
        h,
        y2 + py,
    )

    crop = frame[
        y1:y2,
        x1:x2
    ]

    if crop.size == 0:
        return None

    scale = (
        target_w
        / crop.shape[1]
    )

    new_h = min(
        max_h,
        int(
            crop.shape[0]
            * scale
        ),
    )

    return cv2.resize(
        crop,
        (
            target_w,
            max(
                1,
                new_h,
            ),
        ),
        interpolation=cv2.INTER_LINEAR,
    )


def _paste_eye_inset(
    frame,
    inset,
) -> None:

    h, w = frame.shape[:2]

    ih, iw = inset.shape[:2]

    x0 = (
        w
        - iw
        - 20
    )

    y0 = (
        h
        - ih
        - 55
    )

    if x0 < 0 or y0 < 0:
        return

    cv2.rectangle(
        frame,
        (
            x0 - 2,
            y0 - 2,
        ),
        (
            x0 + iw + 2,
            y0 + ih + 2,
        ),
        CYAN,
        2,
    )

    frame[
        y0:y0 + ih,
        x0:x0 + iw
    ] = inset

    _text(
        frame,
        "eyes",
        (
            x0 + 4,
            y0 + 18,
        ),
        CYAN,
        0.5,
        1,
    )


def _draw_detector_debug(
    frame,
    reading,
    machine_state,
):
    """Show exactly what the new fusion detector is seeing."""

    h = frame.shape[0]

    ear_3d = getattr(
        reading,
        "ear_3d",
        0.0,
    )

    relative_ear = getattr(
        reading,
        "relative_ear",
        1.0,
    )

    blink_left = getattr(
        reading,
        "blink_left_score",
        0.0,
    )

    blink_right = getattr(
        reading,
        "blink_right_score",
        0.0,
    )

    look_up = getattr(
        reading,
        "look_up_score",
        0.0,
    )

    look_down = getattr(
        reading,
        "look_down_score",
        0.0,
    )

    gaze_blocked = bool(
        getattr(
            reading,
            "gaze_blocked",
            False,
        )
    )

    blink_candidate = bool(
        getattr(
            reading,
            "blink_candidate",
            False,
        )
    )

    blink_detected = bool(
        getattr(
            reading,
            "blink_detected",
            False,
        )
    )

    blink_duration = float(
        getattr(
            reading,
            "blink_duration_ms",
            0.0,
        )
        or 0.0
    )

    # Background panel
    _panel(
        frame,
        15,
        h - 245,
        465,
        h - 105,
        alpha=0.62,
    )

    _text(
        frame,
        (
            f"3D EAR {ear_3d:.3f}    "
            f"REL {relative_ear:.3f}"
        ),
        (
            25,
            h - 215,
        ),
        WHITE,
        0.57,
        1,
    )

    _text(
        frame,
        (
            f"BLINK L {blink_left:.2f}    "
            f"R {blink_right:.2f}"
        ),
        (
            25,
            h - 188,
        ),
        CYAN,
        0.57,
        1,
    )

    _text(
        frame,
        (
            f"LOOK UP {look_up:.2f}    "
            f"DOWN {look_down:.2f}"
        ),
        (
            25,
            h - 161,
        ),
        CYAN,
        0.57,
        1,
    )

    # -------------------------------------------------------------
    # Decision line
    # -------------------------------------------------------------

    if gaze_blocked:

        status = (
            "GAZE BLOCKED - IGNORE SIGNAL"
        )

        color = RED

    elif blink_detected:

        status = (
            "BLINK CONFIRMED "
            f"{blink_duration:.0f} ms"
        )

        color = GREEN

    elif blink_candidate:

        status = (
            "BLINK CANDIDATE"
        )

        color = YELLOW

    elif (
        machine_state.in_episode
        and machine_state.episode_both
    ):

        # Old 2D EAR sees a closure,
        # but robust detector has NOT approved it.
        status = (
            "2D EAR LOW - NOT CONFIRMED"
        )

        color = RED

    else:

        status = "TRACKING"

        color = GREEN

    _text(
        frame,
        status,
        (
            25,
            h - 128,
        ),
        color,
        0.62,
        2,
    )


def draw_hud(
    frame,
    reading,
    machine_state,
    runtime,
    engine,
    suggestions: List[str],
    show_reference: bool,
    typing_enabled: bool,
    fps: float,
    show_eyes: bool = True,
    zoom_enabled: bool = False,
    mode: str = "assist",
    alert_title: str = "",
    alert_detail: str = "",
    pending_pattern: str = "",
    recording: bool = False,
    pattern_notice: str = "",
) -> None:

    h, w = frame.shape[:2]
    global frame_size
    frame_size = (w, h)
    buttons.clear()

    if alert_title:
        _panel(frame, 40, h // 2 - 110, w - 40, h // 2 + 110, alpha=0.88)
        _text(frame, alert_title, (70, h // 2 - 20), RED, 1.7, 4)
        detail = alert_detail or "SIMULATED — not a real 911 call"
        _text(frame, detail[:70], (70, h // 2 + 40), YELLOW, 0.95, 2)

    # Capture eye crop before drawing overlays.
    eye_inset = (
        _make_eye_inset(
            frame,
            reading,
        )
        if (
            show_eyes
            and reading.found
        )
        else None
    )

    # -------------------------------------------------------------
    # Eye tracking display
    # -------------------------------------------------------------

    if reading.found:

        if reading.roi is not None:

            rx, ry, rw, rh = (
                reading.roi
            )

            cv2.rectangle(
                frame,
                (
                    rx,
                    ry,
                ),
                (
                    rx + rw,
                    ry + rh,
                ),
                YELLOW,
                1,
                cv2.LINE_AA,
            )

        _draw_eyes(
            frame,
            reading,
            runtime,
        )

        _draw_openness_bar(
            frame,
            reading,
            runtime,
        )

        _draw_detector_debug(
            frame,
            reading,
            machine_state,
        )

    else:

        _text(
            frame,
            "No face detected",
            (
                30,
                h - 140,
            ),
            RED,
            0.8,
            2,
        )

    # -------------------------------------------------------------
    # Top panel
    # -------------------------------------------------------------

    _panel(
        frame,
        0,
        0,
        w,
        230 if mode != "assist" else 200,
        alpha=0.72,
    )

    cur = (
        engine.symbol_buffer
    )

    live_char = (
        morse.decode(cur)
    )

    live_str = (
        live_char
        if live_char
        else (
            "?"
            if cur
            else ""
        )
    )

    if mode == "assist":
        blinks = pending_pattern or ("listening" if recording else "waiting")
        _text(frame, "RECORDING" if recording else "ASSIST", (20, 48), GREEN, 1.15, 3)
        _text(frame, "Blinks: " + blinks, (20, 100), WHITE, 1.15, 3)
        if pattern_notice:
            _text(frame, pattern_notice, (20, 148), RED, 0.65, 2)
        elif recording:
            _text(frame, "Click Use pattern when the blinks are finished", (20, 148), YELLOW, 0.7, 2)
        else:
            _text(
                frame,
                "1 second after you stop, only the longest match, for 5 seconds",
                (20, 148),
                YELLOW,
                0.7,
                2,
            )
    else:
        _text(
            frame,
            f"Morse: {_symbols_pretty(cur) or '---'}  -> {live_str}",
            (20, 36),
            CYAN,
            0.85,
            2,
        )
        max_chars = max(10, (w - 40) // 18)
        shown = engine.display_text().strip()
        cleaned = engine.cleaned_preview()
        _text(frame, "Raw: " + (shown[-max_chars:] if shown else "_"), (20, 82), GREY, 0.85, 2)
        _text(frame, "Cleaned: " + (cleaned[-max_chars:] if cleaned else "_"), (20, 118), WHITE, 1.05, 2)

    if mode != "assist" and suggestions:

        sug = "   ".join(
            f"{i + 1}.{s}"
            for i, s
            in enumerate(
                suggestions
            )
        )

        _text(
            frame,
            "Choose: " + sug,
            (20, 150),
            GREEN,
            0.75,
            2,
        )

        pick = getattr(engine, "right_picks", 0)
        hint = (
            f"(right x{pick} -> #{pick})"
            if pick
            else "(right wink x1 #1, x2 #2, x3 #3)"
        )
        _text(
            frame,
            hint,
            (20, 186),
            YELLOW,
            0.6,
            1,
        )

    # -------------------------------------------------------------
    # Flash message
    # -------------------------------------------------------------

    flash = (
        engine.active_flash()
    )

    if flash:

        _text(
            frame,
            flash,
            (
                w // 2 - 120,
                h // 2,
            ),
            RED,
            1.0,
            3,
        )

    # -------------------------------------------------------------
    # Status
    # -------------------------------------------------------------

    _text(
        frame,
        f"{fps:0.0f} FPS",
        (
            w - 120,
            30,
        ),
        GREY,
        0.6,
        1,
    )

    tstat = (
        "TYPING:ON"
        if typing_enabled
        else "typing:off"
    )

    _text(
        frame,
        tstat,
        (
            w - 170,
            55,
        ),
        (
            GREEN
            if typing_enabled
            else GREY
        ),
        0.6,
        1,
    )

    mode_label = "ASSIST" if mode == "assist" else "MORSE"
    _text(
        frame,
        mode_label,
        (w - 220, 115),
        GREEN if mode == "assist" else CYAN,
        0.95,
        2,
    )

    zstat = (
        "ZOOM:ON"
        if zoom_enabled
        else "zoom:off"
    )

    _text(
        frame,
        zstat,
        (
            w - 170,
            80,
        ),
        (
            GREEN
            if zoom_enabled
            else GREY
        ),
        0.6,
        1,
    )

    # -------------------------------------------------------------
    # Controls
    # -------------------------------------------------------------

    _panel(frame, 0, h - 96, w, h, alpha=0.78)
    _button(frame, "customize", 16, h - 78, 200, 58, "Customize", BUTTON)
    mode_btn = "Switch to Morse" if mode == "assist" else "Switch to Assist"
    _button(frame, "mode", 228, h - 78, 250, 58, mode_btn, BUTTON_ALT)
    if mode != "assist":
        _button(frame, "send", 490, h - 78, 200, 58, "Send", BUTTON)
        record_x = 710
    else:
        record_x = 490
    record_label = "Use pattern" if recording else "Record blinks"
    _button(frame, "record", record_x, h - 78, 230, 58, record_label, BUTTON)
    _text(frame, "q quit   Enter send", (record_x + 246, h - 40), WHITE, 0.65, 2)

    if show_reference:
        _draw_reference(
            frame
        )

    if eye_inset is not None:

        _paste_eye_inset(
            frame,
            eye_inset,
        )


def _draw_reference(
    frame,
) -> None:

    rows = (
        morse.reference_rows()
    )

    cols = 4

    per_col = (
        len(rows)
        + cols
        - 1
    ) // cols

    cw = 170
    chh = 26
    pad = 14

    pw = (
        cols * cw
        + pad * 2
    )

    ph = (
        per_col * chh
        + pad * 2
        + 30
    )

    x0 = (
        frame.shape[1]
        - pw
        - 20
    )

    y0 = 190

    _panel(
        frame,
        x0,
        y0,
        x0 + pw,
        y0 + ph,
        alpha=0.75,
    )

    _text(
        frame,
        "MORSE REFERENCE",
        (
            x0 + pad,
            y0 + 24,
        ),
        YELLOW,
        0.7,
        2,
    )

    for i, (
        ch,
        code,
    ) in enumerate(rows):

        c = (
            i // per_col
        )

        r = (
            i % per_col
        )

        x = (
            x0
            + pad
            + c * cw
        )

        y = (
            y0
            + pad
            + 44
            + r * chh
        )

        _text(
            frame,
            f"{ch} {code}",
            (
                x,
                y,
            ),
            WHITE,
            0.6,
            1,
        )