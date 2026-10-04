"""Local page for editing blink shortcuts.

Runs beside the camera window. The user can type a dot/dash pattern, or record
the next live blinks, then bind that pattern to a simulated SOS alert or a
message destination.
"""

from __future__ import annotations

import threading

import config
from shortcuts import Shortcut, ShortcutMatcher, pattern_owner

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blink shortcuts</title>
<style>
  :root {
    --bg: #0e1116;
    --card: #1a1f29;
    --line: #2c3442;
    --text: #f4f7fb;
    --muted: #a7b0be;
    --gold: #f5c542;
    --green: #3dd68c;
    --danger: #ff6b6b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", sans-serif;
    background: radial-gradient(1200px 500px at 10% -10%, #243044, var(--bg));
    color: var(--text);
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }
  header h1 { font-size: 34px; margin: 0 0 8px; }
  header p { margin: 0; color: var(--muted); max-width: 680px; line-height: 1.45; }
  .banner {
    margin-top: 18px; background: #3a3114; color: var(--gold);
    border-radius: 12px; padding: 12px 16px;
  }
  .layout {
    display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 20px; margin-top: 24px;
  }
  @media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
  .card {
    background: var(--card); border: 1px solid var(--line);
    border-radius: 16px; padding: 20px;
  }
  h2 { margin: 0 0 6px; font-size: 18px; }
  .hint { color: var(--muted); font-size: 14px; line-height: 1.45; margin: 0 0 16px; }
  .live {
    font-family: Consolas, monospace; font-size: 28px;
    letter-spacing: 0.08em; color: var(--green); min-height: 42px;
  }
  .row-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
  button {
    border: 0; border-radius: 10px; padding: 10px 14px; font: inherit; cursor: pointer;
  }
  button.primary { background: var(--gold); color: #1a1404; font-weight: 650; }
  button.ghost { background: #2a3140; color: var(--text); }
  button.danger { background: transparent; color: var(--danger); }
  .shortcut {
    display: grid; grid-template-columns: 1fr auto; gap: 8px 12px;
    border-top: 1px solid var(--line); padding: 14px 0;
  }
  .shortcut strong { display: block; font-size: 18px; }
  .pattern { font-family: Consolas, monospace; font-size: 22px; letter-spacing: 0.08em; margin-top: 4px; }
  .meta { color: var(--muted); font-size: 13px; margin-top: 4px; }
  label { display: block; margin-top: 12px; color: var(--muted); font-size: 13px; }
  input, select {
    width: 100%; margin-top: 6px; padding: 11px 12px; border-radius: 10px;
    border: 1px solid var(--line); background: #12161d; color: var(--text); font: inherit;
  }
  input:focus, select:focus { outline: 2px solid var(--gold); border-color: transparent; }
  .warn { display: none; margin: 8px 0 0; color: var(--danger); font-size: 14px; line-height: 1.4; }
  .warn.show { display: block; }
  .empty { color: var(--muted); }
  .side { display: flex; flex-direction: column; gap: 8px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Blink shortcuts</h1>
    <p>Name a pattern of dots and dashes, then choose the words that appear on the camera. The app waits one second after the last blink and shows only the longest match.</p>
    <div class="banner">Simulated alerts only. Nothing on this page calls or texts 911.</div>
  </header>
  <div class="layout">
    <section class="card">
      <h2>Saved shortcuts</h2>
      <p class="hint">Demo location: <strong id="location"></strong></p>
      <div id="rows"></div>
    </section>
    <section class="card">
      <h2>Create a shortcut</h2>
      <p class="hint">A dot is a short blink. A dash is held past 250 ms. For several dashes, allow about 1000 ms between blinks and 5000 ms for the whole gesture.</p>
      <div class="live" id="live">idle</div>
      <div class="row-actions">
        <button type="button" class="ghost" id="record">Record blinks</button>
        <button type="button" class="ghost" id="stop">Use as pattern</button>
      </div>
      <form id="form">
        <label>Name<input name="name" required value="SOS"></label>
        <label>Pattern<input name="pattern" required value="..." placeholder=". and -"></label>
        <p class="warn" id="pattern-warn" role="alert"></p>
        <label>Pause allowed between blinks (ms)<input name="max_gap_ms" type="number" value="400"></label>
        <label>Whole gesture limit (ms)<input name="max_span_ms" type="number" value="1500"></label>
        <label>What happens
          <select name="action">
            <option value="sos">Simulated SOS</option>
            <option value="message">Show a message</option>
          </select>
        </label>
        <label>Words on screen<input name="message" value="Emergency assist requested"></label>
        <label>Destination<input name="destination" value="Nearest police station (simulated)"></label>
        <div class="row-actions"><button class="primary" type="submit">Save shortcut</button></div>
      </form>
    </section>
  </div>
</div>
<script>
function pretty(pattern) {
  return (pattern || "").replaceAll(".", "● ").replaceAll("-", "— ").trim();
}
function fill(row) {
  const form = document.getElementById("form");
  for (const key of ["name", "pattern", "max_gap_ms", "max_span_ms", "action", "message", "destination"]) {
    if (form.elements[key]) form.elements[key].value = row[key] ?? "";
  }
}
async function refresh() {
  const data = await (await fetch("/api/state")).json();
  document.getElementById("location").textContent = data.demo_location;
  const live = document.getElementById("live");
  const pattern = data.recorded_pattern || "";
  live.textContent = data.recording ? (pretty(pattern) || "listening") : (pretty(pattern) || "idle");
  if (data.form_pattern) {
    hidePatternWarning();
    document.querySelector("[name=pattern]").value = data.form_pattern;
    fetch("/api/ack-form", {method: "POST"});
  }
  const body = document.getElementById("rows");
  body.replaceChildren();
  if (!data.shortcuts.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No shortcuts yet.";
    body.appendChild(empty);
    return;
  }
  for (const row of data.shortcuts) {
    const card = document.createElement("article");
    card.className = "shortcut";
    const main = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = row.name;
    const pat = document.createElement("div");
    pat.className = "pattern";
    pat.textContent = pretty(row.pattern);
    const raw = document.createElement("div");
    raw.className = "meta";
    raw.textContent = row.pattern;
    const meta = document.createElement("div");
    meta.className = "meta";
    const kind = row.action === "sos" ? "Simulated SOS" : "Message";
    meta.textContent = kind + " · pause " + row.max_gap_ms + " ms · gesture " + row.max_span_ms + " ms";
    const words = document.createElement("div");
    words.className = "meta";
    words.textContent = row.message || "";
    main.append(title, pat, raw, meta, words);
    const actions = document.createElement("div");
    actions.className = "side";
    const edit = document.createElement("button");
    edit.className = "ghost";
    edit.type = "button";
    edit.textContent = "Edit";
    edit.onclick = () => { hidePatternWarning(); fill(row); };
    const del = document.createElement("button");
    del.className = "danger";
    del.type = "button";
    del.textContent = "Delete";
    del.onclick = async () => {
      await fetch("/api/delete", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({pattern: row.pattern, name: row.name})});
      refresh();
    };
    actions.append(edit, del);
    card.append(main, actions);
    body.appendChild(card);
  }
}
function showPatternWarning(owner, pattern) {
  const warn = document.getElementById("pattern-warn");
  const input = document.querySelector("[name=pattern]");
  warn.textContent = pattern + " is already used by " + owner + ". Enter a new pattern.";
  warn.classList.add("show");
  input.value = "";
  input.focus();
}
function hidePatternWarning() {
  const warn = document.getElementById("pattern-warn");
  warn.textContent = "";
  warn.classList.remove("show");
}
document.getElementById("form").onsubmit = async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target).entries());
  const response = await fetch("/api/save", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) {
    if (data.owner) showPatternWarning(data.owner, payload.pattern);
    else {
      const warn = document.getElementById("pattern-warn");
      warn.textContent = data.error || "Could not save.";
      warn.classList.add("show");
    }
    return;
  }
  hidePatternWarning();
  refresh();
};
document.getElementById("record").onclick = async () => {
  await fetch("/api/record", {method: "POST"});
  refresh();
};
document.getElementById("stop").onclick = async () => {
  const name = document.querySelector("[name=name]").value;
  const data = await (await fetch("/api/stop", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name})
  })).json();
  if (data.owner) showPatternWarning(data.owner, data.pattern || "");
  else if (data.pattern) {
    hidePatternWarning();
    document.querySelector("[name=pattern]").value = data.pattern;
  }
  refresh();
};
refresh();
setInterval(refresh, 500);
</script>
</body>
</html>
"""


def _parse_shortcut(payload: dict) -> Shortcut:
    pattern = "".join(ch for ch in str(payload.get("pattern", "")) if ch in ".-")
    action = str(payload.get("action", "message"))
    if action not in ("sos", "message"):
        action = "message"
    return Shortcut(
        name=str(payload.get("name", pattern or "shortcut")).strip() or "shortcut",
        pattern=pattern,
        max_gap_ms=float(payload.get("max_gap_ms") or config.SOS_MAX_GAP_MS),
        max_span_ms=float(payload.get("max_span_ms") or config.SOS_MAX_SPAN_MS),
        action=action,
        message=str(payload.get("message", "")),
        destination=str(payload.get("destination", "")),
    )


def start_workspace(matcher: ShortcutMatcher) -> None:
    """Serve the editor in a background thread. Missing Flask only prints a note."""
    try:
        from flask import Flask, jsonify, request
    except ImportError:
        print("Workspace page needs Flask. Install it with: pip install flask")
        return

    app = Flask(__name__)

    @app.get("/")
    def index():
        return PAGE

    @app.get("/api/state")
    def state():
        return jsonify(matcher.snapshot())

    @app.post("/api/save")
    def save():
        incoming = _parse_shortcut(request.get_json(force=True) or {})
        if not incoming.pattern:
            return jsonify({"ok": False, "error": "pattern must use . and -"}), 400
        current = [Shortcut(**row) for row in matcher.snapshot()["shortcuts"]]
        owner = pattern_owner(current, incoming.pattern, incoming.name)
        if owner:
            return jsonify({
                "ok": False,
                "owner": owner,
                "error": f"{incoming.pattern} is already used by {owner}. Enter a new pattern.",
            }), 409
        replaced = False
        updated = []
        for row in current:
            if row.name == incoming.name:
                updated.append(incoming)
                replaced = True
            else:
                updated.append(row)
        if not replaced:
            updated.append(incoming)
        matcher.save(updated)
        return jsonify({"ok": True})

    @app.post("/api/delete")
    def delete():
        payload = request.get_json(force=True) or {}
        name = str(payload.get("name", ""))
        pattern = str(payload.get("pattern", ""))
        current = [Shortcut(**row) for row in matcher.snapshot()["shortcuts"]]
        kept = [row for row in current if not (row.name == name and row.pattern == pattern)]
        matcher.save(kept)
        return jsonify({"ok": True})

    @app.post("/api/ack-form")
    def ack_form():
        matcher.take_form_pattern()
        return jsonify({"ok": True})

    @app.post("/api/record")
    def record():
        matcher.start_recording()
        return jsonify({"ok": True})

    @app.post("/api/stop")
    def stop():
        payload = request.get_json(silent=True) or {}
        pattern = matcher.stop_recording()
        current = [Shortcut(**row) for row in matcher.snapshot()["shortcuts"]]
        owner = pattern_owner(current, pattern, str(payload.get("name", "")))
        return jsonify({"ok": True, "pattern": pattern, "owner": owner})

    def run() -> None:
        app.run(host="127.0.0.1", port=config.WORKSPACE_PORT, threaded=True, use_reloader=False)

    threading.Thread(target=run, daemon=True).start()
    print(f"Shortcut workspace: http://127.0.0.1:{config.WORKSPACE_PORT}")
