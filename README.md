# RowdyHackXII — Hands-Free Eye-Blink Morse Communication

RowdyHackXII is an accessibility-focused prototype that turns intentional eye blinks into Morse-style text. A person can compose a message hands-free, keep their raw Morse text or deliberately accept an offered correction, and send only the confirmed final line to a trusted live text room.

The project supports two complementary experiences:

- **Assist mode**: fast, configurable blink shortcuts for prewritten needs such as a simulated SOS or “I need help.”
- **Morse mode**: short and long bilateral blinks compose text letter by letter; the final confirmed line can appear on another trusted device in a local conversation room.

Camera processing stays on the sender’s device. The room server receives only text after the sender chooses **Send** or presses **Enter**.

> **Prototype disclaimer:** This is a hackathon accessibility prototype, not a medically validated communication device, emergency system, encrypted messenger, or replacement for established assistive technology. Simulated SOS actions do not call or text 911.

---

## What it does

```text
Sender laptop
  webcam
    ↓
MediaPipe Face Landmarker
    ↓
eye landmarks + EAR + blink/wink state machine
    ↓
Assist shortcut or Morse text composition
    ↓
explicit confirmation
    ↓
confirmed text only
    ↓
Trusted Text Room server
    ↓
receiver browser on another device
```

The system does **not** send:

- Webcam video
- Camera frames
- Face landmarks
- Eye Aspect Ratio values
- Blink or wink events
- Calibration values
- Unfinished Morse patterns
- Unconfirmed message drafts

### Core flow

1. **Track**: MediaPipe identifies face and eyelid landmarks from the local webcam.
2. **Measure**: The app calculates per-eye Eye Aspect Ratio (EAR) values and uses blink/gaze signals to distinguish intentional input from noise.
3. **Calibrate**: A guided local calibration records the person’s natural open and gently closed eye states.
4. **Compose**: Bilateral blinks become Morse dots and dashes. A pause finalizes a letter.
5. **Review**: The raw Morse line remains visible. Cleanup or word suggestions are offered as choices; corrections are never silently applied.
6. **Confirm**: The sender clicks **Send** or presses **Enter**.
7. **Deliver**: Only the final text on screen is optionally typed into the focused app and/or published to a trusted local room.

---

## Modes

### Assist mode

Assist mode is the default. It recognizes saved dot/dash patterns and triggers a configured local demo action.

The default shortcut is three fast dots:

```text
...
```

It creates a **simulated SOS alert** and records a local demo event. It does not contact emergency services.

You can edit or record Assist patterns through the local shortcut workspace:

```text
http://127.0.0.1:8765
```

### Morse mode

Morse mode composes letter-by-letter text from intentional bilateral blinks.

The app preserves the raw line by default.

For example:

```text
Raw Morse line: helo
Choice 1:        helo
Choice 2:        HELLO
```

The sender must explicitly choose the offered correction. Sending never autocorrects text automatically.

---

## Blink language

| Gesture | Meaning |
|---|---|
| Short bilateral blink, about 40–250 ms | Add Morse dot (`.`) |
| Long bilateral blink, more than 250 ms | Add Morse dash (`-`) |
| Eyes open for about 0.7 seconds | Finish the current Morse letter |
| `Space` key | Insert a word break |
| Left wink, more than 300 ms | Backspace |
| One right wink, then selection pause | Choose option #1: keep raw line |
| Two right winks, then selection pause | Choose option #2: accept correction or first suggestion |
| Three right winks, then selection pause | Choose option #3, if shown |
| `m` key or mode button | Switch between Assist and Morse modes |

Blinks shorter than about 40 ms are ignored as likely camera noise. A closure from 40–250 ms is a dot; a longer closure is a dash.

A pause ends a **letter**, not a word. Use the space key for intentional word breaks.

---

## Requirements

- Windows, macOS, or Linux
- Python 3.12 recommended
- Git
- Webcam
- Local network access for the two-device Trusted Text Room demo
- Flask for the local shortcut workspace and room server

The project has been tested with Python 3.12.10.

---

## Setup

Clone and create a virtual environment:

```powershell
git clone [https://github.com/jasonpham2002/RowdyHackXII.git](https://github.com/jasonpham2002/RowdyHackXII.git)
cd RowdyHackXII
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The MediaPipe Face Landmarker model is included at:

```text
models/face_landmarker.task
```

If the model is missing:

```powershell
python download_model.py
```

Verify Flask if you want to use the shortcut workspace or Trusted Text Room:

```powershell
python -c "import flask; print('Flask OK')"
```

---

## Run locally

Start the camera app:

```powershell
python main.py
```

This opens the webcam, guides calibration, and starts in **Assist mode**.

Start directly in Morse mode:

```powershell
python main.py --morse
```

Useful startup options:

```powershell
python main.py --skip-calib
python main.py --morse
python main.py --type
python main.py --camera 1
python main.py --no-zoom
python main.py --no-save
```

| Command | Meaning |
|---|---|
| `--skip-calib` | Reuse `calibration.json`, or defaults if none exists |
| `--morse` | Start in Morse mode instead of Assist mode |
| `--type` | Type the confirmed final message into the focused application |
| `--camera 1` | Use a different webcam index |
| `--no-zoom` | Disable eye-region zoom and detect from the full frame |
| `--no-save` | Do not save updated calibration values |

---

## Calibration

During calibration:

1. Sit facing the camera in even front lighting.
2. Keep your head still.
3. Hold your eyes naturally open for the open-eye capture.
4. Gently close your eyes for the closed-eye capture.
5. Do not force your eyes wide open.

Press `Esc` during calibration to skip it and use default values.

Press `c` while the app runs to recalibrate after changing lighting, webcam position, or seating distance.

If an old calibration file behaves poorly, delete it or recalibrate:

```powershell
Remove-Item .\calibration.json -ErrorAction SilentlyContinue
```

---

## Keyboard and buttons

Keep the OpenCV camera window focused for keyboard controls.

| Key | Action |
|---|---|
| `q` or `Esc` | Quit |
| `o` | Open the local shortcut workspace |
| `m` | Toggle Assist and Morse modes |
| `Enter` | Send the current confirmed Morse line |
| `c` | Recalibrate |
| `r` | Toggle Morse reference chart |
| `e` | Toggle eye inset panel |
| `z` | Toggle eye-region zoom |
| `t` | Toggle optional OS typing |
| `[` or `-` | Lower close threshold |
| `]` or `=` | Raise close threshold |
| `Backspace` | Delete last Morse letter or character |
| `Space` | Finalize the current word and insert a space |

On-screen buttons include:

- **Customize**
- **Switch to Assist / Morse**
- **Record blinks** in Assist mode
- **Use pattern** while recording
- **Send** in Morse mode

---

## Shortcut workspace

The app starts a local Flask workspace for editing saved Assist shortcuts.

While `main.py` is running, open:

```text
http://127.0.0.1:8765
```

Or press:

```text
o
```

The workspace is intentionally bound to the local machine. It is for configuring the sender application, not for a receiver to join a conversation.

Use the workspace to:

- Create or edit Assist shortcut names
- Enter dot/dash patterns
- Configure message or demo action details
- Check for duplicate patterns
- Save shortcuts to `shortcuts.json`

A pattern already used by another shortcut is rejected. The application prefers the longest valid pattern after the configured hold period, preventing `...` and `....` from both firing for the same gesture.

---

## Trusted Text Room

The Trusted Text Room is the two-device conversation demo.

The room server stores messages only in memory while it runs. It receives **confirmed text only**.

### 1. Start the room server

On the laptop that will host the room:

```powershell
python .\chat_server.py --host 0.0.0.0 --port 8766
```

Keep that terminal open.

`0.0.0.0` makes the server listen on the host laptop’s network interfaces so another device on the same reachable LAN can open the room. The receiver must use the host laptop’s actual LAN IP address, not `127.0.0.1`. Binding a server to `0.0.0.0` makes it reachable through the host’s available IPv4 interfaces. [95][97]

### 2. Find the host laptop IP

On the host laptop:

```powershell
Get-NetIPAddress -InterfaceAlias "Wi-Fi" -AddressFamily IPv4 |
Where-Object {
    $_.IPAddress -notlike "169.254.*" -and
    $_.IPAddress -notlike "127.*"
} |
Format-Table InterfaceAlias, IPAddress, PrefixLength
```

Example result:

```text
InterfaceAlias  IPAddress      PrefixLength
--------------  ---------      ------------
Wi-Fi            10.188.29.234 17
```

### 3. Open the same room on both devices

On the host laptop, this local URL works:

```text
http://127.0.0.1:8766/?room=ROWDY1
```

On the receiver laptop or phone, use the host laptop’s LAN IP:

```text
http://10.188.29.234:8766/?room=ROWDY1
```

Replace `10.188.29.234` with the address discovered on the host.

Both devices must use the same room code:

```text
ROWDY1
```

### 4. Start the Morse sender

If the camera sender runs on the **same laptop as the room server**:

```powershell
python .\main.py --morse --room ROWDY1 --sender-name "Eye Morse" --room-server "http://127.0.0.1:8766"
```

If the camera sender runs on a **different laptop** from the room server, use the host laptop LAN address:

```powershell
python .\main.py --morse --room ROWDY1 --sender-name "Sender" --room-server "http://10.188.29.234:8766"
```

The sender uses `127.0.0.1` only when the sender and server run on the same computer. A different laptop must point to the host laptop’s reachable LAN IP.

### 5. Send a message

1. Compose Morse text.
2. Keep the raw text or deliberately choose a correction.
3. Click **Send** or press `Enter`.
4. The app publishes only the confirmed visible line.
5. The receiver browser refreshes and shows the message.

The app uses Python’s standard-library `urllib.request` for the local HTTP publish call; `requests` is not required. Python’s `urllib.request.Request` supports POST requests with encoded request data. [92][94]

### LAN test

Before relying on the room in a demo, verify the host can be reached from the receiver laptop:

```powershell
Test-NetConnection <HOST_LAPTOP_IP> -Port 8766
```

Example:

```powershell
Test-NetConnection 10.188.29.234 -Port 8766
```

A successful result:

```text
TcpTestSucceeded : True
```

If the host is reachable but the browser does not load, ensure the room server is still running and allow Python through Windows Firewall on the appropriate network profile.

### Eduroam note

Some managed Wi-Fi networks isolate client devices. If two devices cannot reach each other on eduroam, use a private hotspot or a Windows Mobile Hotspot for the demo. Test the LAN connection before presenting.

---

## Tuning

Timing and threshold settings live in `config.py`.

| Setting | Meaning |
|---|---|
| `DOT_MAX_MS` | Maximum bilateral closure duration treated as a dot |
| `LETTER_GAP_MS` | Open-eye pause that commits the current letter |
| `SHORTCUT_HOLD_MS` | Assist-mode wait after the final blink before selecting the longest match |
| `ASSIST_SHOW_S` | How long an Assist or sent-message alert remains visible |
| `RIGHT_PICK_MAX_MS` | Maximum duration of a right-wink suggestion selection |
| `RIGHT_SELECT_GAP_MS` | Delay after right-wink selections before applying a choice |
| `BLINK_MIN_MS` | Minimum bilateral closure duration that counts |
| `CLOSE_RATIO` | Position of the calibrated close threshold between open and closed eye values |
| `DEFAULT_CLOSE_THRESH` | Default close threshold when calibration is skipped |

During a demo, use `[` and `]` to adjust sensitivity more quickly than editing configuration files. Calibration changes are saved in `calibration.json` unless `--no-save` is used.

---

## Tests

Run without a camera:

```powershell
python .\test_smoke.py
python .\test_shortcuts.py
python .\test_cleaner.py
python .\test_choices.py
```

| Test | Coverage |
|---|---|
| `test_smoke.py` | Morse decoding, prediction, state-machine dots/dashes/gaps/winks, natural-blink handling, MediaPipe model load |
| `test_shortcuts.py` | Assist shortcut matching and pattern behavior |
| `test_cleaner.py` | Conservative Morse cleanup, jammed phrases, acronyms, and mild corrections |
| `test_choices.py` | Raw-text preservation and explicit right-wink correction/suggestion choices |

---

## Project layout

| File | Role |
|---|---|
| `main.py` | Camera loop, modes, event routing, buttons, confirmed-send flow |
| `chat_server.py` | In-memory Flask Trusted Text Room server |
| `chat_client.py` | Standard-library HTTP publisher for confirmed text |
| `workspace.py` | Local Flask shortcut editor at `127.0.0.1:8765` |
| `actions.py` | Simulated SOS and local action/message display |
| `shortcuts.py` | Assist pattern storage and matching |
| `shortcuts.json` | Persisted Assist shortcuts |
| `tracker.py` | MediaPipe landmarks, EAR signals, blendshape and gaze information, eye zoom |
| `robust_blink_detector.py` | Temporal 3D-EAR blink candidate validation |
| `calibration.py` | Per-user open/closed eye calibration |
| `state_machine.py` | Dot, dash, letter gap, wink, and cooldown logic |
| `morse.py` | Morse lookup table and decoder |
| `predictor.py` | Local word completion suggestions |
| `cleaner.py` | Conservative cleaned-text preview offered as a choice |
| `hud.py` | Camera overlay, buttons, feedback, diagnostics |
| `typer.py` | Optional OS typing after confirmed Send |
| `config.py` | Camera, timing, threshold, and port settings |
| `download_model.py` | Downloads the Face Landmarker model if needed |
| `test_smoke.py` | Core non-camera test coverage |
| `test_shortcuts.py` | Assist shortcut tests |
| `test_cleaner.py` | Cleanup behavior tests |
| `test_choices.py` | Correction-choice behavior tests |

---

## Privacy and limitations

- Camera processing runs locally on the sender device.
- The Trusted Text Room receives only sender-confirmed final text.
- Room messages are retained only in server memory until the room server stops.
- The room is a local hackathon demo and does not claim end-to-end encryption, account security, durable message storage, or emergency reliability.
- Accurate detection depends on lighting, camera frame rate, camera placement, eye visibility, calibration, and the person’s ability to intentionally blink or wink.
- Independent left/right wink control may not be comfortable or possible for every person.
- The project should be presented as an accessibility-focused prototype, not a medical device.

---

## Demo checklist

```text
[ ] Start chat_server.py on the room host
[ ] Verify receiver browser can open the host room URL
[ ] Start main.py in Morse mode with matching room/server flags
[ ] Confirm no normal resting-eye false inputs
[ ] Blink-compose a short message
[ ] Keep raw text or explicitly choose an offered correction
[ ] Press Send or Enter
[ ] Verify the receiver browser shows only the confirmed text
[ ] Explain: “The camera stays local; only confirmed text enters the room.”
```