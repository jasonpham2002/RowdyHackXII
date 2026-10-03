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


def _text(frame, s, org, color=WHITE, scale=0.7, thick=2):
    cv2.putText(frame, s, org, FONT, scale, (0, 0, 0), thick + 3, cv2.LINE_AA)
    cv2.putText(frame, s, org, FONT, scale, color, thick, cv2.LINE_AA)


def _panel(frame, x1, y1, x2, y2, alpha=0.55):
    sub = frame[y1:y2, x1:x2]
    if sub.size == 0:
        return
    overlay = np.full_like(sub, PANEL)
    frame[y1:y2, x1:x2] = cv2.addWeighted(overlay, alpha, sub, 1 - alpha, 0)


def _draw_eyes(frame, reading, runtime):
    for ring, closed in ((reading.left_ring, reading.open_left < runtime.close_thresh_left),
                         (reading.right_ring, reading.open_right < runtime.close_thresh_right)):
        if not ring:
            continue
        pts = np.array(ring, dtype=np.int32)
        cv2.polylines(frame, [pts], True, RED if closed else GREEN, 2, cv2.LINE_AA)


def _draw_openness_bar(frame, reading, runtime):
    """Horizontal EAR meter with the close threshold marked."""
    x, y, w, h = 30, frame.shape[0] - 70, 300, 22
    _text(frame, "EAR", (x, y - 8), GREY, 0.6, 1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), GREY, 1)
    # Auto-scale the bar to the EAR range.
    max_v = max(0.45, runtime.open_mean * 1.4, runtime.close_thresh * 1.6)
    val = min(reading.open_avg, max_v) / max_v
    fill = int(w * val)
    closed = reading.open_avg < runtime.close_thresh
    cv2.rectangle(frame, (x, y), (x + fill, y + h),
                  RED if closed else GREEN, -1)
    tx = x + int(w * min(runtime.close_thresh, max_v) / max_v)
    cv2.line(frame, (tx, y - 4), (tx, y + h + 4), YELLOW, 2)
    _text(frame, f"{reading.open_avg:0.3f}", (x + w + 12, y + h - 3), WHITE, 0.6, 1)
    _text(frame, f"thr {runtime.close_thresh:0.3f}  [ ]=sensitivity",
          (x, y - 28), YELLOW, 0.55, 1)


def _symbols_pretty(symbols: str) -> str:
    return "".join("DOT " if c == "." else "DASH " for c in symbols).strip()


def _make_eye_inset(frame, reading, pad_ratio=0.6, target_w=300, max_h=150):
    """Return a zoomed-in crop around both eyes (from the clean frame)."""
    pts = list(reading.left_ring) + list(reading.right_ring)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    bw, bh = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return None
    px = int(bw * pad_ratio)
    py = int(bh * (pad_ratio + 0.6))
    h, w = frame.shape[:2]
    x1 = max(0, x1 - px)
    y1 = max(0, y1 - py)
    x2 = min(w, x2 + px)
    y2 = min(h, y2 + py)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    scale = target_w / crop.shape[1]
    new_h = min(max_h, int(crop.shape[0] * scale))
    return cv2.resize(crop, (target_w, max(1, new_h)), interpolation=cv2.INTER_LINEAR)


def _paste_eye_inset(frame, inset) -> None:
    h, w = frame.shape[:2]
    ih, iw = inset.shape[:2]
    x0 = w - iw - 20
    y0 = h - ih - 55
    if x0 < 0 or y0 < 0:
        return
    # Border + label.
    cv2.rectangle(frame, (x0 - 2, y0 - 2), (x0 + iw + 2, y0 + ih + 2), CYAN, 2)
    frame[y0:y0 + ih, x0:x0 + iw] = inset
    _text(frame, "eyes", (x0 + 4, y0 + 18), CYAN, 0.5, 1)


def draw_hud(frame, reading, machine_state, runtime, engine,
             suggestions: List[str], show_reference: bool,
             typing_enabled: bool, fps: float, show_eyes: bool = True) -> None:
    h, w = frame.shape[:2]

    # Capture the eye close-up from the clean frame BEFORE drawing overlays.
    eye_inset = _make_eye_inset(frame, reading) if (show_eyes and reading.found) else None

    if reading.found:
        _draw_eyes(frame, reading, runtime)
        _draw_openness_bar(frame, reading, runtime)
    else:
        _text(frame, "No face detected", (30, h - 55), RED, 0.8, 2)

    # ---- Top panel: current symbol + decoded text ----------------------
    _panel(frame, 0, 0, w, 170)
    cur = engine.symbol_buffer
    live_char = morse.decode(cur)
    live_str = live_char if live_char else ("?" if cur else "")
    _text(frame, f"Morse: {_symbols_pretty(cur) or '---'}  -> {live_str}",
          (20, 40), CYAN, 0.9, 2)

    typed = engine.display_text()
    # Wrap the typed text so it never runs off screen.
    max_chars = max(10, (w - 40) // 18)
    shown = typed[-max_chars:]
    _text(frame, "Text: " + (shown if shown else "_"), (20, 85), WHITE, 0.9, 2)

    if suggestions:
        sug = "   ".join(f"{i+1}.{s}" for i, s in enumerate(suggestions))
        _text(frame, "Suggest: " + sug, (20, 125), GREEN, 0.75, 2)
        _text(frame, "(right wink = accept #1)", (20, 155), GREY, 0.55, 1)

    # ---- Closure progress (dot vs dash feedback) -----------------------
    if machine_state.in_episode and machine_state.episode_both:
        ms = machine_state.closure_ms
        kind = "DOT" if ms <= config.DOT_MAX_MS else "DASH"
        color = GREEN if kind == "DOT" else YELLOW
        _text(frame, f"holding... {kind} ({ms:0.0f} ms)", (20, h - 100), color, 0.8, 2)

    # ---- Flash message (e.g. unknown sequence) -------------------------
    flash = engine.active_flash()
    if flash:
        _text(frame, flash, (w // 2 - 120, h // 2), RED, 1.0, 3)

    # ---- Status line (top-right) ---------------------------------------
    _text(frame, f"{fps:0.0f} FPS", (w - 120, 30), GREY, 0.6, 1)
    tstat = "TYPING:ON" if typing_enabled else "typing:off"
    _text(frame, tstat, (w - 170, 55), GREEN if typing_enabled else GREY, 0.6, 1)

    # ---- Help line (bottom) --------------------------------------------
    _text(frame,
          "[q]uit [c]alibrate [r]ef [e]yes [t]ype [backspace]=del [space]=space",
          (20, h - 20), GREY, 0.55, 1)

    if show_reference:
        _draw_reference(frame)

    if eye_inset is not None:
        _paste_eye_inset(frame, eye_inset)


def _draw_reference(frame) -> None:
    rows = morse.reference_rows()
    cols = 4
    per_col = (len(rows) + cols - 1) // cols
    cw, chh = 170, 26
    pad = 14
    pw = cols * cw + pad * 2
    ph = per_col * chh + pad * 2 + 30
    x0 = frame.shape[1] - pw - 20
    y0 = 190
    _panel(frame, x0, y0, x0 + pw, y0 + ph, alpha=0.75)
    _text(frame, "MORSE REFERENCE", (x0 + pad, y0 + 24), YELLOW, 0.7, 2)
    for i, (ch, code) in enumerate(rows):
        c = i // per_col
        r = i % per_col
        x = x0 + pad + c * cw
        y = y0 + pad + 44 + r * chh
        _text(frame, f"{ch} {code}", (x, y), WHITE, 0.6, 1)
