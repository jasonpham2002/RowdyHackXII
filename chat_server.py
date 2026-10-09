"""Trusted text room server for the RowdyHacks demo.

The server receives only confirmed text messages. It never receives webcam
frames, facial landmarks, blink events, calibration values, or unfinished
Morse drafts.

Accounts and confirmed messages are stored in PostgreSQL. Set DATABASE_URL
before starting the server.

Run directly:
    python chat_server.py --host 0.0.0.0 --port 8766
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session

import db
from chat_client import lan_url, load_session, save_session


app = Flask(__name__)
_FONT_DIR = Path(__file__).resolve().parent / "presentation" / "fonts"
_FONT_FILES = {"cinzel-latin.woff2", "josefin-latin.woff2"}


def _secret_key() -> str:
    configured = os.environ.get("SECRET_KEY", "").strip()
    if configured:
        return configured
    path = Path(__file__).resolve().with_name(".room_secret")
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    generated = secrets.token_hex(32)
    try:
        path.write_text(generated, encoding="utf-8")
    except OSError:
        pass
    return generated


app.secret_key = _secret_key()


def normalize_room(value: str) -> str:
    room = "".join(char for char in value.upper() if char.isalnum())
    return room[:12] or "ROWDY1"


def room_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


@app.get("/fonts/<name>")
def font_file(name: str):
    if name not in _FONT_FILES:
        return "", 404
    return send_from_directory(_FONT_DIR, name)


@app.get("/")
def room_page():
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Operation Morse — Text room</title>
  <style>
    @font-face {
      font-family: Cinzel;
      font-style: normal;
      font-weight: 700;
      font-display: swap;
      src: url("/fonts/cinzel-latin.woff2") format("woff2");
    }
    @font-face {
      font-family: "Josefin Sans";
      font-style: normal;
      font-weight: 400;
      font-display: swap;
      src: url("/fonts/josefin-latin.woff2") format("woff2");
    }
    :root {
      color-scheme: dark;
      --color-primary: #31616f;
      --color-background: #1a1c1b;
      --color-foreground: #f6e7d4;
      --color-card: #27484f;
      --color-muted: #c5d4d6;
      --color-iris: #9ed8d4;
      --color-wine: #581828;
      --font-heading: Cinzel, "Palatino Linotype", Palatino, serif;
      --font-body: "Josefin Sans", "Segoe UI", sans-serif;
      --font-mono: "Cascadia Mono", Consolas, ui-monospace, monospace;
    }
    * { box-sizing: border-box; }
    html { overflow-x: clip; }
    body {
      margin: 0;
      min-height: 100vh;
      background-color: var(--color-background);
      background-image:
        linear-gradient(rgba(39, 72, 79, 0.45) 1px, transparent 1px),
        linear-gradient(90deg, rgba(39, 72, 79, 0.45) 1px, transparent 1px);
      background-size: 64px 64px;
      color: var(--color-foreground);
      font-family: var(--font-body);
      font-size: 18px;
      line-height: 1.5;
    }
    .top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 16px;
      width: min(880px, calc(100% - 48px));
      margin: 0 auto;
      padding: 28px 0 8px;
    }
    .top > div { min-width: 0; }
    .kicker {
      margin: 0;
      color: var(--color-iris);
      font-family: var(--font-mono);
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    h1 {
      margin: 4px 0 0;
      font-family: var(--font-heading);
      font-size: 36px;
      font-weight: 700;
      line-height: 1;
    }
    .stamp {
      margin: 0;
      padding: 10px 16px;
      border: 2px solid var(--color-wine);
      background: var(--color-wine);
      color: var(--color-foreground);
      font-family: var(--font-mono);
      letter-spacing: 0.06em;
    }
    main {
      width: min(880px, calc(100% - 48px));
      margin: 0 auto;
      padding: 16px 0 64px;
      display: grid;
      gap: 24px;
    }
    h1, h2, p, .privacy, #status, #account-status, .text, #share { overflow-wrap: anywhere; }
    #account-status { min-height: 28px; margin: 12px 0 0; }
    .frame {
      position: relative;
      padding: 28px 32px 32px;
      background: rgba(39, 72, 79, 0.94);
      border: 2px solid var(--color-primary);
      box-shadow: 0 0 0 8px rgba(26, 28, 27, 0.35);
    }
    .frame::before,
    .frame::after,
    .message::before,
    .message::after {
      content: "";
      position: absolute;
      width: 18px;
      height: 18px;
      border: 2px solid var(--color-iris);
      pointer-events: none;
    }
    .frame::before, .message::before {
      top: -8px;
      left: -8px;
      border-right: 0;
      border-bottom: 0;
    }
    .frame::after, .message::after {
      right: -8px;
      bottom: -8px;
      border-left: 0;
      border-top: 0;
    }
    .index {
      display: inline-block;
      margin-bottom: 12px;
      padding: 4px 10px;
      background: var(--color-wine);
      font-family: var(--font-mono);
      letter-spacing: 0.12em;
    }
    h2 {
      margin: 0 0 12px;
      font-family: var(--font-heading);
      font-size: 40px;
      font-weight: 700;
      line-height: 1.05;
    }
    .lead, .privacy, #status, .empty { color: var(--color-foreground); }
    .privacy {
      margin: 16px 0 0;
      padding: 12px 14px;
      border-left: 4px solid var(--color-wine);
      background: #1a1c1b;
    }
    .controls { display: grid; gap: 14px; margin-top: 20px; }
    label {
      display: grid;
      gap: 8px;
      color: var(--color-muted);
    }
    .actions { display: flex; gap: 12px; flex-wrap: wrap; }
    input, button {
      min-height: 48px;
      border: 2px solid var(--color-primary);
      padding: 12px 16px;
      font: inherit;
      color: var(--color-foreground);
    }
    input { width: 100%; max-width: 100%; background: #1a1c1b; }
    input:focus {
      outline: none;
      border-color: var(--color-iris);
      box-shadow: 0 0 0 3px rgba(158, 216, 212, 0.35);
    }
    button {
      cursor: pointer;
      background: var(--color-wine);
      border-color: var(--color-wine);
      font-weight: 600;
      transition: background 200ms ease, color 200ms ease;
    }
    button.secondary { background: transparent; border-color: var(--color-iris); color: var(--color-iris); }
    button.secondary:hover { background: var(--color-iris); color: #1a1c1b; }
    #share {
      margin: 16px 0 0;
      padding: 12px 14px;
      border: 2px solid var(--color-iris);
      background: #1a1c1b;
      color: var(--color-iris);
      font-family: var(--font-mono);
      word-break: break-all;
    }
    #status { min-height: 28px; margin-bottom: 8px; }
    #messages { display: grid; gap: 14px; }
    .message {
      position: relative;
      padding: 14px 16px;
      background: #1a1c1b;
      border: 2px solid var(--color-primary);
    }
    .sender { color: var(--color-iris); font-family: var(--font-mono); font-weight: 600; }
    .time { color: var(--color-muted); font-size: 0.85rem; margin-left: 8px; }
    .text { margin-top: 6px; font-size: 1.15rem; white-space: pre-wrap; }
    .empty { padding: 8px 0 0; }
    :focus-visible { outline: 2px solid var(--color-iris); outline-offset: 3px; }
    @media (max-width: 640px) {
      h1 { font-size: 28px; }
      h2 { font-size: 32px; }
      .frame { padding: 22px 18px 24px; }
      .actions { flex-direction: column; }
      .actions button { width: 100%; }
    }
    @media (prefers-reduced-motion: reduce) {
      * { transition: none; }
    }
  </style>
</head>
<body>
  <header class="top">
    <div>
      <p class="kicker">RowdyHack XII</p>
      <h1>Operation Morse</h1>
    </div>
    <p class="stamp" id="stamp">Text room</p>
  </header>
  <main>
    <section class="frame" id="account-frame">
      <span class="index">01</span>
      <h2>Account</h2>
      <p class="lead">Log in here. This page and the camera on this laptop share that login.</p>
      <form id="account-form" class="controls">
        <label>Email
          <input id="email" type="email" maxlength="254" autocomplete="username" required>
        </label>
        <label>Password
          <input id="password" type="password" minlength="8" maxlength="200" autocomplete="current-password" required>
        </label>
        <label>Display name
          <input id="display-name" maxlength="40" autocomplete="nickname" placeholder="Shown on each line">
        </label>
        <div class="actions">
          <button type="button" id="register">Create account</button>
          <button type="submit" class="secondary" id="login">Log in</button>
          <button type="button" class="secondary" id="logout">Log out</button>
        </div>
      </form>
      <p id="account-status">Create an account or log in before opening a room.</p>
    </section>
    <section class="frame">
      <span class="index">02</span>
      <h2>Open a room</h2>
      <p class="lead">One laptop hosts. The other pastes the share link, logs in on that host, and joins. The camera sends a line only after you confirm it.</p>
      <div class="privacy">
        Camera processing stays on the sender's device. This room receives only
        text after the sender confirms it.
      </div>
      <form id="setup" class="controls">
        <label>Your name
          <input id="name" maxlength="40" value="Eye Morse" autocomplete="nickname">
        </label>
        <label>Room code
          <input id="room" maxlength="12" value="ROWDY1" placeholder="ROWDY1">
        </label>
        <label>Host link, for the other laptop
          <input id="link" placeholder="http://10.0.0.12:8766/?room=ROWDY1">
        </label>
        <div class="actions">
          <button type="button" id="host">Host this room</button>
          <button type="button" class="secondary" id="join">Join a room</button>
        </div>
      </form>
      <p id="share" hidden></p>
    </section>
    <section class="frame">
      <span class="index">03</span>
      <h2>Confirmed lines</h2>
      <div id="status">Log in, then host a room or join one.</div>
      <form id="compose" class="controls">
        <label>Send a confirmed line
          <input id="outgoing" maxlength="500" autocomplete="off" placeholder="Visible text to share">
        </label>
        <div class="actions">
          <button type="submit" id="send-line">Send</button>
        </div>
      </form>
      <section id="messages" aria-live="polite"></section>
    </section>
  </main>

  <script>
    const nameInput = document.getElementById("name");
    const roomInput = document.getElementById("room");
    const linkInput = document.getElementById("link");
    const hostButton = document.getElementById("host");
    const joinButton = document.getElementById("join");
    const share = document.getElementById("share");
    const status = document.getElementById("status");
    const messages = document.getElementById("messages");
    const stamp = document.getElementById("stamp");
    const onThisLaptop = location.hostname === "localhost" || location.hostname === "127.0.0.1";

    const emailInput = document.getElementById("email");
    const passwordInput = document.getElementById("password");
    const displayNameInput = document.getElementById("display-name");
    const accountStatus = document.getElementById("account-status");
    const outgoingInput = document.getElementById("outgoing");

    let room = "";
    let serverUrl = location.origin;
    let latestId = "";
    let role = "host";
    let authToken = sessionStorage.getItem("blinkchilling-token") || "";

    function normalizedRoom(value) {
      return value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 12) || "ROWDY1";
    }

    function showShare(url, code) {
      share.hidden = false;
      share.textContent = "Share this link: " + url.replace(/[/]$/, "") + "/?room=" + code;
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

    function originOf(value) {
      const text = String(value || "").trim();
      if (!text) return "";
      try {
        return new URL(text.includes("://") ? text : "http://" + text).origin;
      } catch (error) {
        return "";
      }
    }

    function authBase() {
      const pasted = originOf(linkInput.value);
      if (pasted) return pasted;
      if (role === "join") {
        const joined = originOf(serverUrl);
        if (joined) return joined;
      }
      return location.origin;
    }

    function messageBase() {
      if (onThisLaptop && role !== "join") return location.origin.replace(/[/]$/, "");
      return serverUrl.replace(/[/]$/, "");
    }

    async function refresh() {
      if (!room) return;
      if (!authToken) {
        status.textContent = "Log in to see confirmed lines.";
        return;
      }

      try {
        const base = messageBase();
        const response = await fetch(`${base}/api/rooms/${encodeURIComponent(room)}/messages`, {
          headers: {"Authorization": "Bearer " + authToken}
        });
        const payload = await response.json();
        if (!response.ok) {
          status.textContent = payload.error || "Could not load the room.";
          return;
        }

        render(payload.messages || []);

        if (payload.messages && payload.messages.length) {
          latestId = payload.messages[payload.messages.length - 1].id;
        }

        status.textContent = `Connected to room ${room} at ${serverUrl}. Waiting for confirmed text...`;
      } catch {
        status.textContent = "Connection lost. Retrying...";
      }
    }

    function applySession(saved) {
      role = saved.role === "join" ? "join" : "host";
      room = normalizedRoom(saved.room || roomInput.value);
      serverUrl = (saved.server_url || location.origin).replace(/[/]$/, "");
      roomInput.value = room;
      if (saved.name) {
        nameInput.value = saved.name;
        if (!displayNameInput.value) displayNameInput.value = saved.name;
      }
      if (typeof saved.token === "string") {
        authToken = saved.token;
        if (authToken) sessionStorage.setItem("blinkchilling-token", authToken);
        else sessionStorage.removeItem("blinkchilling-token");
      }
      if (role === "join" && serverUrl) {
        linkInput.value = serverUrl + "/?room=" + room;
      }
      latestId = "";
      if (role === "host") showShare(serverUrl, room);
      else share.hidden = true;
      stamp.textContent = room;
      refresh();
    }

    async function saveSession(nextRole) {
      role = nextRole;
      const response = await fetch("/api/session", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          name: nameInput.value,
          room: normalizedRoom(roomInput.value),
          role: role,
          server_url: role === "join" ? (linkInput.value || serverUrl) : "",
          token: authToken
        })
      });
      const saved = await response.json();
      if (!response.ok) {
        status.textContent = saved.error || "Could not save the room.";
        return;
      }
      applySession(saved);
    }

    async function showAccount() {
      if (!authToken) {
        accountStatus.textContent = "Create an account or log in before opening a room.";
        return;
      }
      try {
        const response = await fetch(authBase() + "/api/me", {
          headers: {"Authorization": "Bearer " + authToken}
        });
        const payload = await response.json();
        if (response.status === 401) {
          authToken = "";
          sessionStorage.removeItem("blinkchilling-token");
          accountStatus.textContent = payload.error || "Log in again to use the room.";
          if (onThisLaptop) await saveSession(role);
          return;
        }
        if (!response.ok) {
          accountStatus.textContent = payload.error || "Account server is unavailable.";
          return;
        }
        const displayName = (payload.user && payload.user.displayName) || "";
        accountStatus.textContent = displayName ? "Logged in as " + displayName + "." : "Logged in.";
        if (displayName) {
          displayNameInput.value = displayName;
          if (nameInput.value !== displayName) {
            nameInput.value = displayName;
            if (onThisLaptop) await saveSession(role);
          }
        }
      } catch {
        accountStatus.textContent = "Account server is unavailable.";
      }
    }

    async function submitAccount(path) {
      const base = authBase();
      accountStatus.textContent = "Checking the account...";
      try {
        const response = await fetch(base + path, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            email: emailInput.value.trim(),
            password: passwordInput.value,
            displayName: displayNameInput.value.trim() || nameInput.value.trim()
          })
        });
        const payload = await response.json();
        if (!response.ok) {
          accountStatus.textContent = payload.error || "Could not log in.";
          return;
        }
        authToken = payload.token || "";
        if (authToken) sessionStorage.setItem("blinkchilling-token", authToken);
        const displayName = (payload.user && payload.user.displayName) || "";
        if (displayName) {
          nameInput.value = displayName;
          displayNameInput.value = displayName;
        }
        accountStatus.textContent = displayName ? "Logged in as " + displayName + "." : "Logged in.";
        passwordInput.value = "";
        if (!onThisLaptop) {
          refresh();
          return;
        }
        const local = location.origin.replace(/[/]$/, "");
        if (base.replace(/[/]$/, "") !== local) await saveSession("join");
        else await saveSession("host");
      } catch {
        accountStatus.textContent = "Account server is unavailable.";
      }
    }

    async function logout() {
      const base = authBase();
      const token = authToken;
      authToken = "";
      sessionStorage.removeItem("blinkchilling-token");
      try {
        await fetch(base + "/api/logout", {
          method: "POST",
          headers: token ? {"Authorization": "Bearer " + token} : {}
        });
      } catch {
        // Clear the laptop session even when the account server is offline.
      }
      accountStatus.textContent = "Logged out.";
      passwordInput.value = "";
      if (onThisLaptop) await saveSession(role);
      else {
        render([]);
        status.textContent = "Log in to see confirmed lines.";
      }
    }

    async function sendLine() {
      const text = outgoingInput.value.trim();
      if (!authToken) {
        status.textContent = "Log in before sending.";
        return;
      }
      if (!room) {
        status.textContent = "Host a room or join one before sending.";
        return;
      }
      if (!text) return;
      try {
        const base = messageBase();
        const response = await fetch(`${base}/api/rooms/${encodeURIComponent(room)}/messages`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + authToken
          },
          body: JSON.stringify({text: text})
        });
        const payload = await response.json();
        if (!response.ok) {
          status.textContent = payload.error || "Could not send.";
          return;
        }
        outgoingInput.value = "";
        refresh();
      } catch {
        status.textContent = "Connection lost. Retrying...";
      }
    }

    function requireToken() {
      if (authToken) return true;
      accountStatus.textContent = linkInput.value.trim()
        ? "Paste the host link, then log in. That account is stored on the host."
        : "Log in before opening a room.";
      return false;
    }

    document.getElementById("account-form").addEventListener("submit", (event) => {
      event.preventDefault();
      submitAccount("/api/login");
    });
    document.getElementById("register").addEventListener("click", () => submitAccount("/api/register"));
    document.getElementById("logout").addEventListener("click", logout);
    document.getElementById("compose").addEventListener("submit", (event) => {
      event.preventDefault();
      sendLine();
    });
    document.getElementById("setup").addEventListener("submit", (event) => event.preventDefault());

    hostButton.addEventListener("click", () => {
      if (requireToken()) saveSession("host");
    });
    joinButton.addEventListener("click", () => {
      if (requireToken()) saveSession("join");
    });

    const preset = new URLSearchParams(location.search).get("room");
    if (!onThisLaptop) {
      document.getElementById("setup").hidden = true;
      role = "join";
      room = normalizedRoom(preset || roomInput.value);
      stamp.textContent = room;
      serverUrl = location.origin;
      status.textContent = "Log in to view this room. To send from your camera, paste this address into Join on your laptop.";
      showAccount();
      refresh();
    } else {
      fetch("/api/session").then((response) => response.json()).then((saved) => {
        if (preset) saved.room = normalizedRoom(preset);
        applySession(saved);
        showAccount();
      });
    }

    setInterval(refresh, 900);
  </script>
</body>
</html>
"""


@app.after_request
def _allow_room_pages(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.before_request
def _answer_preflight():
    if request.method == "OPTIONS":
        return "", 204
    return None


def _from_this_laptop() -> bool:
    return request.remote_addr in ("127.0.0.1", "::1")


def _read_json() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def _database_error(exc: db.DatabaseUnavailable):
    return jsonify({"error": str(exc)}), 503


def _user_json(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "displayName": user["display_name"],
    }


def _credentials_present() -> bool:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer ") and header.split(" ", 1)[1].strip():
        return True
    return bool(session.get("user_id"))


def _current_user():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
        if not token:
            return None
        return db.user_from_token(token)
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.get_user(int(user_id))


def _require_user():
    if not _credentials_present():
        return None, (jsonify({"error": "Log in before using the room."}), 401)
    try:
        user = _current_user()
    except db.DatabaseUnavailable as exc:
        return None, _database_error(exc)
    if user is None:
        return None, (jsonify({"error": "Log in before using the room."}), 401)
    return user, None


def _auth_body(user: dict, token: str) -> dict:
    session.clear()
    session["user_id"] = user["id"]
    return {"user": _user_json(user), "token": token}


@app.get("/api/host-info")
def host_info():
    url = lan_url()
    return jsonify({"url": url})


@app.get("/api/session")
def get_session():
    saved = load_session()
    if not _from_this_laptop():
        saved = dict(saved)
        saved["token"] = ""
    return jsonify(saved)


@app.post("/api/session")
def post_session():
    if not _from_this_laptop():
        return jsonify({
            "error": "Set your name on your own laptop. Paste this page into Join there.",
        }), 403
    payload = _read_json()
    role = payload.get("role", "host")
    if role == "join" and not str(payload.get("server_url", "")).strip():
        return jsonify({"error": "Paste the host link from the other laptop."}), 400
    incoming = {
        "name": payload.get("name", ""),
        "room": payload.get("room", ""),
        "role": role,
        "server_url": payload.get("server_url", ""),
    }
    if "token" in payload:
        incoming["token"] = payload.get("token", "")
    saved = save_session(incoming)
    return jsonify(saved)


@app.get("/api/room-code")
def create_room_code():
    return jsonify({"room": room_code()})


@app.post("/api/register")
def register():
    payload = _read_json()
    try:
        user = db.create_user(
            str(payload.get("email", "")),
            str(payload.get("password", "")),
            str(payload.get("displayName") or payload.get("display_name") or ""),
        )
        token = db.issue_token(user["id"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except db.DuplicateEmail:
        return jsonify({"error": "An account with that email already exists."}), 409
    except db.DatabaseUnavailable as exc:
        return _database_error(exc)
    return jsonify(_auth_body(user, token)), 201


@app.post("/api/login")
def login():
    payload = _read_json()
    try:
        user = db.authenticate(
            str(payload.get("email", "")),
            str(payload.get("password", "")),
        )
        if user is None:
            return jsonify({"error": "Email or password is incorrect."}), 401
        token = db.issue_token(user["id"])
    except db.DatabaseUnavailable as exc:
        return _database_error(exc)
    return jsonify(_auth_body(user, token))


@app.post("/api/logout")
def logout():
    header = request.headers.get("Authorization", "")
    token = header.split(" ", 1)[1].strip() if header.lower().startswith("bearer ") else ""
    session.clear()
    try:
        if token:
            db.revoke_token(token)
    except db.DatabaseUnavailable as exc:
        return _database_error(exc)
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    user, failure = _require_user()
    if failure is not None:
        return failure
    return jsonify({"user": _user_json(user)})


@app.get("/api/rooms/<room>/messages")
def get_messages(room: str):
    _user, failure = _require_user()
    if failure is not None:
        return failure
    normalized = normalize_room(room)
    try:
        messages = db.list_messages(normalized)
    except db.DatabaseUnavailable as exc:
        return _database_error(exc)
    return jsonify({"room": normalized, "messages": messages})


@app.post("/api/rooms/<room>/messages")
def post_message(room: str):
    user, failure = _require_user()
    if failure is not None:
        return failure
    normalized = normalize_room(room)
    text = str(_read_json().get("text", "")).strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        message = db.insert_message(normalized, user["id"], user["display_name"], text)
    except db.DatabaseUnavailable as exc:
        return _database_error(exc)
    return jsonify({"room": normalized, "message": message}), 201


def run_server(host: str = "0.0.0.0", port: int = 8766) -> None:
    try:
        db.init_db()
    except db.DatabaseUnavailable as exc:
        print(f"[room] {exc}")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trusted Text Room server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)