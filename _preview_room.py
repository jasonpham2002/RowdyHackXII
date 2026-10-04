"""Open the room page in headless Chrome and exercise Host and Join."""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from chat_server import app

ROOT = Path(__file__).resolve().parent
PORT = 8779
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEBUG_PORT = 9223


def serve() -> None:
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def ws_connect(url: str) -> socket.socket:
    host_port, path = url.removeprefix("ws://").split("/", 1)
    host, port = host_port.split(":")
    sock = socket.create_connection((host, int(port)), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET /{path} HTTP/1.1\r\n"
        f"Host: {host_port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode())
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
    return sock


def ws_send(sock: socket.socket, payload: str) -> None:
    data = payload.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    else:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    sock.sendall(bytes(header) + mask + masked)


def _read(sock: socket.socket, size: int) -> bytes:
    chunks = []
    got = 0
    while got < size:
        piece = sock.recv(size - got)
        if not piece:
            raise EOFError("chrome socket closed")
        chunks.append(piece)
        got += len(piece)
    return b"".join(chunks)


def ws_recv(sock: socket.socket) -> str:
    buffer = b""
    while True:
        first, second = _read(sock, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", _read(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _read(sock, 8))[0]
        if second & 0x80:
            mask = _read(sock, 4)
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(_read(sock, length)))
        else:
            payload = _read(sock, length)
        if opcode == 0x8:
            raise EOFError("chrome closed the debugger")
        if opcode in (0x0, 0x1):
            buffer += payload
            if first & 0x80:
                text = buffer.decode()
                buffer = b""
                return text


def command(sock: socket.socket, message_id: int, method: str, params: dict | None = None):
    ws_send(sock, json.dumps({"id": message_id, "method": method, "params": params or {}}))
    while True:
        payload = json.loads(ws_recv(sock))
        if payload.get("id") == message_id:
            return payload


def evaluate(sock: socket.socket, message_id: int, expression: str):
    result = command(
        sock,
        message_id,
        "Runtime.evaluate",
        {"expression": expression, "awaitPromise": True, "returnByValue": True},
    )
    value = result["result"]["result"]
    if value.get("subtype") == "error":
        raise RuntimeError(value.get("description"))
    return value.get("value")


def main() -> None:
    threading.Thread(target=serve, daemon=True).start()
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("room page did not start")

    profile = ROOT / "_chrome_profile"
    chrome = subprocess.Popen(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        tabs = None
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=1) as response:
                    tabs = json.loads(response.read().decode())
                    break
            except Exception:
                time.sleep(0.2)
        if not tabs:
            raise SystemExit("chrome debugger did not start")
        sock = ws_connect(tabs[0]["webSocketDebuggerUrl"])
        command(sock, 1, "Page.enable")
        command(sock, 2, "Runtime.enable")
        command(
            sock,
            3,
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        command(sock, 4, "Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
        time.sleep(0.8)
        shot = command(sock, 5, "Page.captureScreenshot", {"format": "png"})
        (ROOT / "_room_desktop.png").write_bytes(base64.b64decode(shot["result"]["data"]))

        hosted = evaluate(
            sock,
            6,
            """
            (async () => {
              document.getElementById("host").click();
              await new Promise((resolve) => setTimeout(resolve, 500));
              const share = document.getElementById("share");
              return {
                share: share.textContent,
                hidden: share.hidden,
                status: document.getElementById("status").textContent,
                hostBg: getComputedStyle(document.getElementById("host")).backgroundColor
              };
            })()
            """,
        )
        print("hosted", json.dumps(hosted))
        shot = command(sock, 7, "Page.captureScreenshot", {"format": "png"})
        (ROOT / "_room_hosted.png").write_bytes(base64.b64decode(shot["result"]["data"]))

        joined_blank = evaluate(
            sock,
            8,
            """
            (async () => {
              document.getElementById("link").value = "";
              document.getElementById("join").click();
              await new Promise((resolve) => setTimeout(resolve, 300));
              return document.getElementById("status").textContent;
            })()
            """,
        )
        print("blank join", joined_blank)

        joined = evaluate(
            sock,
            9,
            """
            (async () => {
              document.getElementById("name").value = "Friend";
              document.getElementById("link").value = "http://10.188.29.234:8766/?room=ROWDY1";
              document.getElementById("join").click();
              await new Promise((resolve) => setTimeout(resolve, 500));
              return document.getElementById("status").textContent;
            })()
            """,
        )
        print("joined", joined)

        command(
            sock,
            10,
            "Emulation.setDeviceMetricsOverride",
            {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
        )
        command(sock, 11, "Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
        time.sleep(0.8)
        mobile = evaluate(
            sock,
            12,
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1",
        )
        print("mobile fits", mobile)
        shot = command(sock, 13, "Page.captureScreenshot", {"format": "png"})
        (ROOT / "_room_mobile.png").write_bytes(base64.b64decode(shot["result"]["data"]))
        sock.close()
    finally:
        chrome.kill()


if __name__ == "__main__":
    main()
