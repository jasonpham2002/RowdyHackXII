# RowdyHackXII — Hands-Free Eye-Blink Morse Decoder

A laptop webcam watches your eyes and turns blinks into two kinds of messages. **Assist mode** (the default) fires custom blink shortcuts, such as three fast dots for a simulated SOS. **Morse mode** spells letters one blink at a time and shows the raw line. A cleaned sentence is offered as a choice and is applied only after you pick it.

Built for a 720p HD webcam (1280×720). Alerts are simulated. Nothing in this project calls or texts 911.

## What it does

```
camera → MediaPipe FaceLandmarker → Eye Aspect Ratio (EAR)
      → blink / wink state machine
      → Assist shortcuts, or Morse letters
      → on-screen message (optional: type the confirmed sentence)
```

1. **Track.** MediaPipe finds eyelid landmarks on both eyes.
2. **Measure.** Each eye gets an Eye Aspect Ratio: vertical opening divided by eye width. A closed eye drops toward 0. Because it is a ratio, distance from the camera does not matter much.
3. **Calibrate.** A short guided capture records *your* open and closed EAR for each eye and sets a personal threshold. Narrow or uneven eyes are handled separately.
4. **Assist.** A saved pattern of dots and dashes runs an action. The app waits one second after the last blink, then shows only the longest match for five seconds. Three dots and four dots do not both fire.
5. **Morse.** Hold length decides dot vs dash. A short pause ends a letter. A pause does not insert a space. The screen shows the raw line. When autocorrect would change it, that cleaned line is a right-wink choice and is not applied until you pick it. Other slots are word suggestions, three choices at most. **Send** or Enter sends the line on screen.

Eye zoom is on by default: after the first frame, detection crops and upscales the region around your eyes so small eyes get more pixels. A yellow box shows that region. If the zoomed crop misses your face, it falls back to the full frame.

## Blink language

| Gesture | Meaning |
| --- | --- |
| Short blink, both eyes (~40–250 ms) | Dot |
| Longer blink, both eyes (> 250 ms) | Dash |
| Eyes open ~0.7 s | End the current letter |
| Space key | End the word (insert a space). A pause does not add one. |
| Left wink (> 300 ms) | Backspace |
| Right wink once, then a 3 s pause (Morse) | Keep the raw line (choice #1) |
| Right wink twice, then a 3 s pause (Morse) | Accept choice #2: the cleaned line when autocorrect is offered, otherwise the first word suggestion |
| Right wink 3 times, then a 3 s pause (Morse) | Accept choice #3 when a third choice is listed |
| Each suggestion wink | At most 1 second. A longer right blink does not count. |
| `m` key, or the mode button | Toggle Assist mode and Morse mode |

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

Assist mode watches for custom blink shortcuts. The default shortcut is three fast dots (`...`, each gap under 400 ms), which raises a **simulated SOS** alert and writes a line to `dispatch_log.txt`. It does not call or text 911. Press `m`, or the mode button, to switch to Morse mode for letter-by-letter typing.

While the camera is running, click **Customize** (or press `o`) to open the shortcut page at [http://127.0.0.1:8765](http://127.0.0.1:8765). Type a pattern, or record blinks from that page. In Assist mode the camera also has **Record blinks**. Click it, blink the gesture, then click **Use pattern**. A new pattern is filled into the shortcut page. A dash is a blink held past 250 ms. For several dashes, allow about 1000 ms between blinks and 5000 ms for the whole gesture.

A pattern that another shortcut already uses is refused. Recording it on the camera shows a warning there, such as `... is already used by SOS. Enter a new pattern.` Typing that pattern on the shortcut page shows the same warning under the pattern box and clears it. Saving the shortcut you are editing, with its own current pattern, still works.

In Morse mode the window shows the raw line you blinked. Autocorrect is not applied on its own. When a cleaned sentence would change that line, it appears as choice #2, and the text stays raw until you pick it. Word suggestions fill the remaining slots, three choices at most. Click **Send** or press Enter to send the line on screen. A sent message stays up for five seconds, then the text clears. Assist shortcuts skip this step because their message is already written.

Other ways to start:

```powershell
python main.py --skip-calib    # reuse calibration.json, or defaults if none exists
python main.py --morse         # start in Morse mode instead of Assist
python main.py --type          # on Send, also type the kept line into the focused app
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
| `o` | Open the shortcut page |
| `m` | Toggle Assist and Morse |
| `Enter` | Send the Morse line on screen |
| `c` | Recalibrate |
| `r` | Toggle the Morse reference chart |
| `e` | Toggle the zoomed eye inset |
| `z` | Toggle eye-zoom detection |
| `t` | Toggle OS typing (`pynput`) |
| `[` or `-` | Lower the close threshold (easier to count as open) |
| `]` or `=` | Raise the close threshold |
| `Backspace` | Delete the last letter |
| `Space` | Insert a word break. A pause does not do this. |

On-screen buttons: **Customize**, **Switch to Assist / Morse**, **Record blinks** (Assist mode; it becomes **Use pattern** while recording), and, in Morse mode, **Send**.

In Assist mode the HUD shows the blinks collected so far. In Morse mode it shows the raw line and the right-wink choices. Autocorrect stays in that list until you pick it. Above the buttons, an open/close bar reads **OPEN** in green, or **CLOSED** in red once your eyes pass the yellow line. FPS stays visible in both modes.

## Tuning

All timing and thresholds live in `config.py`. Useful ones:

- `DOT_MAX_MS` — longest close that is still a dot (default 250). Longer than this is a dash.
- `LETTER_GAP_MS` — pause that ends the current letter (default 700). A pause does not insert a space.
- `SHORTCUT_HOLD_MS` — pause after the last Assist blink before the longest pattern wins (default 1000).
- `ASSIST_SHOW_S` — how long an Assist or sent Morse message stays on screen (default 5).
- `RIGHT_PICK_MAX_MS` / `RIGHT_SELECT_GAP_MS` — a suggestion wink must be at most 1 second, then the app waits 3 seconds to choose.
- `BLINK_MIN_MS` — shortest blink that counts (default 40).
- `CLOSE_RATIO` — where the calibrated threshold sits between your open and closed EAR (default 0.62; lower means a lighter wink counts as closed).
- `DEFAULT_CLOSE_THRESH` — used only when you skip calibration (default 0.22).

During a demo, `[` and `]` are faster than editing the file. Changes are saved to `calibration.json`.

## Optional checks

No camera needed:

```powershell
python test_smoke.py
python test_shortcuts.py
python test_cleaner.py
python test_choices.py
```

`test_smoke.py` checks Morse decoding, word suggestions, the blink state machine, and that the face model loads. `test_shortcuts.py` checks Assist patterns. `test_cleaner.py` checks the Morse sentence cleanup. `test_choices.py` checks that autocorrect is a right-wink choice and is not applied until you pick it.

## Project layout

| File | Role |
| --- | --- |
| `main.py` | Camera loop, modes, keyboard and button controls |
| `tracker.py` | FaceLandmarker, EAR, eye zoom |
| `calibration.py` | Open/closed capture and per-eye thresholds |
| `state_machine.py` | Dot, dash, letter gap, winks |
| `shortcuts.py` | Assist pattern matching |
| `shortcuts.json` | Saved blink shortcuts |
| `actions.py` | Simulated SOS and message display |
| `workspace.py` | Shortcut page at `http://127.0.0.1:8765` |
| `cleaner.py` | Morse raw text to a cleaned sentence, offered only as a choice |
| `test_choices.py` | Right-wink raw, autocorrect, and suggestion choices |
| `morse.py` | Morse table |
| `predictor.py` | Word completions (`wordfreq`) |
| `hud.py` | On-screen overlay and buttons |
| `typer.py` | Optional keystrokes into the focused app on Send |
| `config.py` | Tunable numbers |
| `download_model.py` | Fetches the FaceLandmarker model if needed |

## Notes

- Sit in even light, face the camera, and keep your head fairly still. Recalibrate if you move or the room lighting changes.
- OS typing (`--type` or `t`) uses `pynput`. In Morse mode it types the line on screen when you press Send, into whatever window is focused. On Windows this works out of the box; some systems need extra permissions.
- The cleaned line uses `symspellpy`. It keeps spaces you insert with the space key and splits a run of letters that has no space. It is shown as a right-wink choice and replaces the raw line only after you pick it. **Send** does not autocorrect on its own.
- Beeps on dot/dash use Windows `winsound` and are skipped on other platforms.
