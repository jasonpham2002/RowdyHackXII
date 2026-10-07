# BlinkChilling — Hands-Free Eye-Blink Communication

An accessibility-focused communication prototype built for **RowdyHacks XII**.

BlinkChilling uses a laptop webcam to turn intentional eye blinks into messages. **Assist mode** triggers customizable blink shortcuts for predefined messages and simulated alerts. **Morse mode** lets users compose text one letter at a time, review optional spelling corrections and word suggestions, and confirm a message before sending it.

The project uses local computer vision and text-processing tools rather than a generative AI model or API.

> **Prototype notice:** Alerts are simulated. BlinkChilling does not call or text 911 and is not a medical device or a replacement for emergency communication systems.

## Features

- **Webcam-based eye tracking:** MediaPipe FaceLandmarker detects eyelid landmarks for both eyes.
- **Personalized calibration:** Open and closed eye measurements establish separate thresholds for each eye.
- **Assist shortcuts:** Custom dot-and-dash patterns trigger predefined messages or simulated alerts.
- **Morse composition:** Intentional blink duration determines dots and dashes for letter-by-letter input.
- **User-controlled correction:** Sentence cleanup and word suggestions remain optional until explicitly selected.
- **Gesture-based confirmation:** A left wink followed by a right wink sends the displayed Morse line.
- **Shortcut editor:** A local browser interface supports editing, recording, and validating blink patterns.
- **Eye-zoom detection:** The detector crops and upscales the eye region, with a full-frame fallback.
- **Optional OS typing:** Confirmed Morse text can be typed into the focused application.
- **Live feedback:** The HUD displays eye state, collected input, choices, and FPS.

## How it works

```text
Webcam
  → MediaPipe FaceLandmarker
  → Eye Aspect Ratio (EAR)
  → Blink / wink state machine
  → Assist shortcuts or Morse decoding
  → On-screen message
  → Optional typing of confirmed text
```

### Eye tracking and calibration

MediaPipe identifies eyelid landmarks. The app calculates an Eye Aspect Ratio (EAR) for each eye by comparing its vertical opening with its width.

A guided calibration records the user's open and closed EAR values and sets separate thresholds for each eye. This accommodates differences in eye shape and opening, although camera position, lighting, and tracking quality still affect detection.

Eye zoom is enabled by default. After the first frame, the detector crops and upscales the region around the eyes to give that region more pixels. A yellow box marks the detection region. If tracking fails on the crop, detection falls back to the full frame.

### Assist mode

Assist mode matches saved dot-and-dash patterns to actions. The app waits one second after the last blink, selects the longest matching pattern, and displays the resulting message for five seconds.

This prevents overlapping patterns, such as three dots and four dots, from both firing for the same completed gesture.

The default shortcut is three fast dots:

```text
...
```

Each gap must be under 400 ms. The shortcut raises a simulated SOS alert and writes an entry to `dispatch_log.txt`.

### Morse mode

Morse mode converts intentional blink durations into dots and dashes. A short pause completes the current letter, but it does not insert a space.

The HUD displays the raw text. When sentence cleanup would change it, the cleaned version appears as an optional choice rather than replacing the input automatically. Word suggestions fill the remaining slots, with at most three choices displayed.

A left wink followed by a right wink sends the displayed line. The Send button and Enter key perform the same action. The sent message remains visible for five seconds before the text clears.

## Blink and wink controls

| Gesture or input | Meaning |
| --- | --- |
| Short blink with both eyes, approximately 40–250 ms | Dot |
| Longer blink with both eyes, over 250 ms | Dash |
| Eyes open for approximately 0.7 seconds | Complete the current Morse letter |
| Space key | Insert a word break |
| Left wink, then right wink within 2 seconds in Morse mode | Send the displayed line |
| Left wink alone, over 300 ms | Backspace after the 2-second send window |
| One right wink, then a 3-second pause in Morse mode | Keep the raw line, choice #1 |
| Two right winks, then a 3-second pause in Morse mode | Select choice #2: the cleaned line when offered, otherwise the first word suggestion |
| Three right winks, then a 3-second pause in Morse mode | Select choice #3 when available |
| `m` key or mode button | Switch between Assist and Morse modes |

Blinks shorter than approximately 40 ms are ignored as noise. Each right wink used for choice selection must last at most one second; a longer right-eye closure does not count as a selection wink.

Timing values are configurable in `config.py`.

## Requirements

- Windows, macOS, or Linux
- Python 3.12, tested with Python 3.12.10
- A webcam
- Git

The documented camera setup targets a 720p HD webcam at 1280 × 720.

## Setup

### Windows PowerShell

```powershell
git clone [https://github.com/jasonpham2002/RowdyHackXII.git](https://github.com/jasonpham2002/RowdyHackXII.git)
cd RowdyHackXII
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### macOS or Linux

```bash
git clone [https://github.com/jasonpham2002/RowdyHackXII.git](https://github.com/jasonpham2002/RowdyHackXII.git)
cd RowdyHackXII
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### FaceLandmarker model

The model is included at:

```text
models/face_landmarker.task
```

If it is missing, run:

```bash
python download_model.py
```

## Running the application

From the project folder, with the virtual environment activated:

```bash
python main.py
```

The application opens the camera, guides you through calibration, and starts in Assist mode.

Press `m` or use the mode button to switch to Morse mode.

### Launch options

| Option | Behavior |
| --- | --- |
| `--skip-calib` | Reuse `calibration.json`, or use defaults if no calibration exists |
| `--morse` | Start in Morse mode |
| `--type` | Also type the confirmed Morse line into the focused application |
| `--camera 1` | Select a different webcam by index |
| `--no-zoom` | Detect using the full frame only |
| `--no-save` | Do not write calibration to `calibration.json` |

Examples:

```bash
python main.py --morse
python main.py --skip-calib
python main.py --camera 1
python main.py --morse --type
```

## Calibration

Keep your head still and face the camera during calibration.

1. Wait for the countdown.
2. Keep your eyes naturally open for about four seconds. Do not force them wide.
3. Wait for the next countdown.
4. Gently close your eyes for about 2.5 seconds.

Press Esc during calibration to skip and use default thresholds. Press `c` while the application is running to recalibrate.

Recalibrate when lighting, camera position, or your seating position changes. If you have a `calibration.json` from an earlier version, delete it or press `c` to generate thresholds for the current detector.

## Customizing Assist shortcuts

While the camera application is running, click Customize or press `o` to open:

[http://127.0.0.1:8765](http://127.0.0.1:8765)

The shortcut page allows you to enter a pattern manually or record blinks.

### Recording from the camera window

1. Switch to Assist mode.
2. Click Record blinks.
3. Blink the desired dot-and-dash pattern.
4. Click Use pattern.
5. Complete the shortcut details on the browser page and save.

A dash is a blink held longer than 250 ms. For patterns containing several dashes, allow approximately 1000 ms between blinks and 5000 ms for the complete gesture.

### Duplicate-pattern validation

Patterns already assigned to another shortcut are rejected.

For example:

```text
... is already used by SOS. Enter a new pattern.
```

The camera recorder and browser page both report duplicate patterns. Editing an existing shortcut while retaining its own pattern is allowed.

## Keyboard and interface controls

These keyboard controls apply while the camera window is focused.

| Key | Action |
| --- | --- |
| `q` or Esc | Quit |
| `o` | Open the shortcut editor |
| `m` | Toggle Assist and Morse modes |
| Enter | Send the displayed Morse line |
| `c` | Recalibrate |
| `r` | Toggle the Morse reference chart |
| `e` | Toggle the zoomed eye inset |
| `z` | Toggle eye-zoom detection |
| `t` | Toggle OS typing through `pynput` |
| `[` or `-` | Lower the close threshold |
| `]` or `=` | Raise the close threshold |
| Backspace | Delete the last letter |
| Space | Insert a word break |

### On-screen buttons

- Customize
- Switch to Assist / Morse
- Record blinks in Assist mode
- Use pattern while recording
- Send in Morse mode

### HUD feedback

In Assist mode, the HUD displays the collected blink pattern. In Morse mode, it displays the raw line and available right-wink choices.

An eye-state bar displays OPEN in green or CLOSED in red when the measured eye state passes the threshold. FPS remains visible in both modes.

## Text correction and suggestions

Sentence cleanup uses `symspellpy`, while word completions use `wordfreq`.

The cleanup process preserves spaces entered with the Space key and can segment a continuous run of letters. It does not automatically replace the user's input.

When a cleaned sentence differs from the raw line, it appears as choice #2. It replaces the raw line only after selection. Sending a message does not apply correction automatically.

## Tuning

Timing and detection settings are defined in `config.py`.

| Setting | Purpose | Documented default |
| --- | --- | --- |
| `DOT_MAX_MS` | Longest eye closure classified as a dot | 250 ms |
| `LETTER_GAP_MS` | Open-eye pause that completes a Morse letter | 700 ms |
| `SHORTCUT_HOLD_MS` | Assist pause before selecting the longest matching shortcut | 1000 ms |
| `ASSIST_SHOW_S` | Display duration for Assist and sent Morse messages | 5 seconds |
| `RIGHT_PICK_MAX_MS` | Maximum duration of a choice-selection wink | 1000 ms |
| `RIGHT_SELECT_GAP_MS` | Pause before applying the selected wink-count choice | 3000 ms |
| `BLINK_MIN_MS` | Minimum blink duration that counts | 40 ms |
| `CLOSE_RATIO` | Position of the threshold between calibrated open and closed EAR | 0.62 |
| `DEFAULT_CLOSE_THRESH` | Fallback threshold when calibration is skipped | 0.22 |

During a demo, use `[` and `]` to adjust the threshold without editing the configuration file. Threshold changes are saved to `calibration.json`.

## Optional checks

Run these checks from the project folder. They do not require a live camera.

```bash
python test_smoke.py
python test_shortcuts.py
python test_cleaner.py
python test_choices.py
```

| Check | Coverage |
| --- | --- |
| `test_smoke.py` | Morse decoding, word suggestions, blink state machine, and face-model loading |
| `test_shortcuts.py` | Assist shortcut patterns |
| `test_cleaner.py` | Morse sentence cleanup |
| `test_choices.py` | Raw-text, autocorrect, and suggestion choices; correction requires explicit selection |

These are development checks, not evidence of clinical validation or a measured accessibility outcome.

## Project layout

| File | Role |
| --- | --- |
| `main.py` | Application entry point, camera loop, modes, and controls |
| `tracker.py` | MediaPipe FaceLandmarker integration, EAR measurements, and eye zoom |
| `calibration.py` | Open/closed capture and per-eye thresholds |
| `state_machine.py` | Dot, dash, letter-gap, and wink handling |
| `shortcuts.py` | Assist pattern matching |
| `shortcuts.json` | Saved blink shortcuts |
| `actions.py` | Simulated SOS actions and message display |
| `workspace.py` | Local shortcut editor on port 8765 |
| `cleaner.py` | Optional sentence cleanup |
| `morse.py` | Morse-code lookup table |
| `predictor.py` | Word completions through `wordfreq` |
| `hud.py` | On-screen overlay and buttons |
| `typer.py` | Optional keystroke output to the focused application |
| `config.py` | Timing and threshold settings |
| `download_model.py` | FaceLandmarker model download helper |
| `test_smoke.py` | Core smoke checks and model loading |
| `test_shortcuts.py` | Assist-pattern checks |
| `test_cleaner.py` | Sentence-cleanup checks |
| `test_choices.py` | Explicit-selection and suggestion checks |

## Limitations and usage notes

- Use even lighting, face the camera, and keep your head reasonably still.
- Recalibrate after changes in lighting or position.
- Blink detection depends on camera quality, frame rate, eye visibility, and personal calibration.
- Pauses complete letters but do not insert word breaks. Use the Space key to insert a space.
- OS typing uses `pynput` and sends confirmed text to whichever application has focus. Verify the destination before sending.
- Some operating systems require additional permissions for camera access or synthetic keyboard input.
- Dot/dash beeps use Windows `winsound` and are skipped on other platforms.
- Alerts are demonstrations only. No emergency service is contacted.
- This hackathon prototype has not established medical suitability or reliability for safety-critical use.

## Developers

- [Dong Quan Tran](https://github.com/dong-quan-tran)
- [Khoi Anh Le Nguyen](https://github.com/ngkhoi111)
- [Quang Tuong Pham](https://github.com/jasonpham2002)


<!-- Team members: add your preferred name and GitHub profile above. -->
