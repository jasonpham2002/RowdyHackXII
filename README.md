# RowdyHackXII — Hands-Free Eye-Blink Morse Decoder

Type Morse code with your eyes. A laptop webcam watches your face, measures how open each eye is, and turns blinks into dots, dashes, letters, and words — no hands, no keyboard.

Built for a 720p HD webcam (1280×720).

## What it does

```
camera → MediaPipe FaceLandmarker → Eye Aspect Ratio (EAR)
      → blink / wink state machine → Morse decode
      → word suggestions → on-screen text (optional: type into any app)
```

1. **Track.** MediaPipe finds eyelid landmarks on both eyes.
2. **Measure.** Each eye gets an Eye Aspect Ratio: vertical opening divided by eye width. A closed eye drops toward 0. Because it is a ratio, distance from the camera does not matter much.
3. **Calibrate.** A short guided capture records *your* open and closed EAR for each eye and sets a personal threshold. Narrow or uneven eyes are handled separately.
4. **Decode.** Hold length decides dot vs dash. Pauses end a letter or a word.
5. **Speed it up.** After each letter, the top 3 English word completions appear. A right wink accepts the first one.

Eye zoom is on by default: after the first frame, detection crops and upscales the region around your eyes so small eyes get more pixels. A yellow box shows that region. If the zoomed crop misses your face, it falls back to the full frame.

## Blink language

| Gesture | Meaning |
| --- | --- |
| Short blink, both eyes (~40–250 ms) | Dot |
| Longer blink, both eyes (> 250 ms) | Dash |
| Eyes open ~0.7 s | End the current letter |
| Eyes open ~2 s | End the word (insert a space) |
| Left wink (> 300 ms) | Backspace |
| Right wink once (Morse mode) | Accept word suggestion #1 |
| Right wink twice (Morse mode) | Accept word suggestion #2 |
| Right wink 3 times (Morse mode) | Accept word suggestion #3 |
| `m` key | Toggle Assist mode and Morse mode |

Blinks shorter than ~40 ms are ignored (camera noise). A close of 40–250 ms is a dot. Anything held past 250 ms is a dash.

## Requirements

- Windows, macOS, or Linux
- Python 3.12 (tested with 3.12.10)
- A webcam (built-in laptop camera is fine)
- Git

## Setup

```powershell
git clone https://github.com/jasonpham2002/RowdyHackXII.git
cd RowdyHackXII
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On macOS or Linux, activate with `source .venv/bin/activate` instead.

The FaceLandmarker model is already in `models/face_landmarker.task`. If that file is missing, download it:

```powershell
python download_model.py
```

## How to run

From the project folder, with the virtual environment activated:

```powershell
python main.py
```

That opens the camera, walks you through calibration, then starts in **Assist mode**.

Assist mode watches for custom blink shortcuts. The default shortcut is three fast dots (`...`, each gap under 400 ms), which raises a **simulated SOS** alert and writes a line to `dispatch_log.txt`. It does not call or text 911. Press `m` to switch to Morse mode for covert letter-by-letter typing.

While the camera is running, click **Customize** on the camera window (or press `o`) to open the shortcut page at [http://127.0.0.1:8765](http://127.0.0.1:8765). You can type a pattern or record the next blinks from the camera. Assist waits one second after the last blink, shows only the longest matching shortcut, and clears that message after five seconds.

Other ways to start:

```powershell
python main.py --skip-calib    # reuse calibration.json, or defaults if none exists
python main.py --type          # also type confirmed words into the focused app
python main.py --camera 1      # use a different webcam
python main.py --no-zoom       # detect on the full frame only
python main.py --no-save       # do not write calibration.json
```

### Calibration

Keep your head still and look at the camera.

1. Countdown.
2. Eyes **open** at a relaxed, natural width (about 4 seconds). Do not force them wide.
3. Countdown.
4. Eyes **gently closed** (about 2.5 seconds).

Press `Esc` during calibration to skip and use the default threshold. Press `c` later to recalibrate if the lighting or your position changes.

If you have an old `calibration.json` from an earlier version, delete it or press `c` so the threshold matches the current detector.

### Keyboard controls (while the window is focused)

| Key | Action |
| --- | --- |
| `q` or `Esc` | Quit |
| `c` | Recalibrate |
| `r` | Toggle the Morse reference chart |
| `e` | Toggle the zoomed eye inset |
| `z` | Toggle eye-zoom detection |
| `t` | Toggle OS typing (`pynput`) |
| `[` or `-` | Lower the close threshold (easier to count as open) |
| `]` or `=` | Raise the close threshold |
| `Backspace` | Delete |
| `Space` | Finish the current word |

The HUD shows the live Morse buffer, the letter it would become, typed text, word suggestions, an EAR bar with the threshold line, and FPS.

## Tuning

All timing and thresholds live in `config.py`. Useful ones:

- `DOT_MAX_MS` — longest close that is still a dot (default 250). Longer than this is a dash.
- `LETTER_GAP_MS` / `WORD_GAP_MS` — how long to pause to commit a letter or a word
- `BLINK_MIN_MS` — shortest blink that counts (default 120)
- `CLOSE_RATIO` — where the calibrated threshold sits between your open and closed EAR (default 0.62; lower means a lighter wink counts as closed)
- `DEFAULT_CLOSE_THRESH` — used only when you skip calibration (default 0.22)

During a demo, `[` and `]` are faster than editing the file. Changes are saved to `calibration.json`.

## Optional checks

No camera needed:

```powershell
python test_smoke.py
```

That checks Morse decoding, word suggestions, the blink state machine, and that the face model loads.

## Project layout

| File | Role |
| --- | --- |
| `main.py` | Camera loop, text buffer, keyboard controls |
| `tracker.py` | FaceLandmarker, EAR, eye zoom |
| `calibration.py` | Open/closed capture and per-eye thresholds |
| `state_machine.py` | Dot, dash, letter gap, word gap, winks |
| `morse.py` | Morse table |
| `predictor.py` | Word completions (`wordfreq`) |
| `hud.py` | On-screen overlay |
| `typer.py` | Optional keystrokes into the focused app |
| `config.py` | Tunable numbers |
| `download_model.py` | Fetches the FaceLandmarker model if needed |

## Notes

- Sit in even light, face the camera, and keep your head fairly still. Recalibrate if you move or the room lighting changes.
- OS typing (`--type` or `t`) uses `pynput` and types into whatever window is focused. On Windows this works out of the box; some systems need extra permissions.
- Beeps on dot/dash use Windows `winsound` and are skipped on other platforms.
