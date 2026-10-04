"""Small in-memory trusted text room server for the RowdyHacks demo.

The server receives only confirmed text messages. It never receives webcam
frames, facial landmarks, blink events, calibration values, or unfinished
Morse drafts.

Run directly:
    python chat_server.py --host 0.0.0.0 --port 8766
"""

from __future__ import annotations

import argparse
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request


app = Flask(__name__)

_rooms: dict[str, list[dict[str, Any]]] = defaultdict(list)
_lock = threading.Lock()


def normalize_room(value: str) -> str:
    room = "".join(char for char in value.upper() if char.isalnum())
    return room[:12] or "ROWDY1"


def room_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def new_message(sender: str, text: str) -> dict[str, Any]:
    return {
        "id": secrets.token_urlsafe(8),
        "sender": (sender or "Anonymous").strip()[:40] or "Anonymous",
        "text": text.strip()[:500],
        "sentAt": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
def room_page():
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trusted Text Room</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, sans-serif;
    }
    body {
      margin: 0;
      min-height: 100vh;
      background: #10131b;
      color: #f5f7fb;
    }
    main {
      width: min(760px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }
    h1 { margin: 0 0 8px; font-size: 1.7rem; }
    p { color: #b8c1d1; line-height: 1.5; }
    .privacy {
      margin: 18px 0;
      padding: 12px 14px;
      border-left: 4px solid #75d5ff;
      border-radius: 8px;
      background: #17202c;
      color: #d8ecff;
    }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      margin: 20px 0;
    }
    input, button {
      border-radius: 9px;
      border: 1px solid #3c4960;
      padding: 12px;
      font: inherit;
    }
    input { background: #0c1018; color: #fff; }
    button {
      cursor: pointer;
      background: #47b5ff;
      color: #06121d;
      font-weight: 700;
    }
    #status {
      min-height: 24px;
      color: #9aabc1;
      font-size: 0.92rem;
    }
    #messages {
      display: grid;
      gap: 10px;
      margin-top: 18px;
    }
    .message {
      padding: 14px;
      background: #171d29;
      border: 1px solid #273247;
      border-radius: 10px;
    }
    .sender { color: #75d5ff; font-weight: 700; }
    .time { color: #8e9bb0; font-size: 0.8rem; margin-left: 8px; }
    .text { margin-top: 6px; font-size: 1.1rem; white-space: pre-wrap; }
    .empty { color: #8e9bb0; padding: 24px 0; }
  </style>
</head>
<body>
  <main>
    <h1>Trusted Text Room</h1>
    <p>Live, confirmed messages for the Eye Morse demo.</p>
    <div class="privacy">
      Camera processing stays on the sender's device. This room receives only
      text after the sender confirms it.
    </div>

    <div class="controls">
      <input id="room" maxlength="12" value="ROWDY1"
             aria-label="Room code" placeholder="Room code">
      <button id="join">Join room</button>
    </div>

    <div id="status">Choose a room code and join.</div>
    <section id="messages" aria-live="polite"></section>
  </main>

  <script>
    const roomInput = document.getElementById("room");
    const joinButton = document.getElementById("join");
    const status = document.getElementById("status");
    const messages = document.getElementById("messages");

    let room = "";
    let latestId = "";

    function normalizedRoom(value) {
      return value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12) || "ROWDY1";
    }

    function render(items) {
      messages.innerHTML = "";

      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No confirmed messages yet.";
        messages.appendChild(empty);
        return;
      }

      for (const item of items) {
        const card = document.createElement("article");
        card.className = "message";

        const header = document.createElement("div");

        const sender = document.createElement("span");
        sender.className = "sender";
        sender.textContent = item.sender;

        const time = document.createElement("span");
        time.className = "time";
        time.textContent = new Date(item.sentAt).toLocaleTimeString();

        const text = document.createElement("div");
        text.className = "text";
        text.textContent = item.text;

        header.append(sender, time);
        card.append(header, text);
        messages.appendChild(card);
      }
    }

    async function refresh() {
      if (!room) return;

      try {
        const response = await fetch(`/api/rooms/${encodeURIComponent(room)}/messages`);
        const payload = await response.json();

        render(payload.messages || []);

        if (payload.messages && payload.messages.length) {
          latestId = payload.messages[payload.messages.length - 1].id;
        }

        status.textContent = `Connected to room ${room}. Waiting for confirmed text...`;
      } catch {
        status.textContent = "Connection lost. Retrying...";
      }
    }

    function joinRoom() {
      room = normalizedRoom(roomInput.value);
      roomInput.value = room;
      latestId = "";
      history.replaceState({}, "", `/?room=${encodeURIComponent(room)}`);
      refresh();
    }

    joinButton.addEventListener("click", joinRoom);

    roomInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") joinRoom();
    });

    const preset = new URLSearchParams(location.search).get("room");
    roomInput.value = normalizedRoom(preset || roomInput.value);
    joinRoom();

    setInterval(refresh, 900);
  </script>
</body>
</html>
"""


@app.get("/api/room-code")
def create_room_code():
    return jsonify({"room": room_code()})


@app.get("/api/rooms/<room>/messages")
def get_messages(room: str):
    normalized = normalize_room(room)

    with _lock:
        messages = list(_rooms[normalized])

    return jsonify({"room": normalized, "messages": messages})


@app.post("/api/rooms/<room>/messages")
def post_message(room: str):
    normalized = normalize_room(room)
    payload = request.get_json(silent=True) or {}

    text = str(payload.get("text", "")).strip()
    sender = str(payload.get("sender", "Eye Morse"))

    if not text:
        return jsonify({"error": "text is required"}), 400

    message = new_message(sender, text)

    with _lock:
        _rooms[normalized].append(message)
        _rooms[normalized] = _rooms[normalized][-100:]

    return jsonify({"room": normalized, "message": message}), 201


def run_server(host: str = "0.0.0.0", port: int = 8766) -> None:
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trusted Text Room server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)