"""Local HTTP publisher for the Trusted Text Room demo.

Only explicitly confirmed final text is posted to the local room server.
No camera frames, landmarks, calibration data, raw blink events, or unfinished
Morse drafts are transmitted.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

import config


def normalize_room(value: str) -> str:
    room = "".join(char for char in value.upper() if char.isalnum())
    return room[:12] or "ROWDY1"


def lan_ip() -> str:
    """Address other laptops on this network can use to reach this machine."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def lan_url(port: int = config.ROOM_PORT) -> str:
    return f"http://{lan_ip()}:{port}"


def parse_room_link(value: str) -> tuple[str, str]:
    """Split a pasted room link into ``(server_url, room)``.

    Room is empty when the link has no ``room`` query.
    """
    text = value.strip()
    if not text:
        return "", ""
    if "://" not in text:
        text = "http://" + text
    parsed = urllib.parse.urlparse(text)
    if not parsed.netloc:
        return "", ""
    query = urllib.parse.parse_qs(parsed.query)
    room = normalize_room(query["room"][0]) if query.get("room") else ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/"), room


def default_session() -> dict:
    url = f"http://127.0.0.1:{config.ROOM_PORT}"
    return {
        "name": "Eye Morse",
        "room": "ROWDY1",
        "server_url": url,
        "role": "host",
    }


def load_session(path=None) -> dict:
    session_path = path or config.ROOM_SESSION_FILE
    session = default_session()
    try:
        saved = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return session
    if not isinstance(saved, dict):
        return session
    name = str(saved.get("name", session["name"])).strip()[:40]
    room = normalize_room(str(saved.get("room", session["room"])))
    server_url = str(saved.get("server_url", session["server_url"])).strip().rstrip("/")
    role = saved.get("role", session["role"])
    session["name"] = name or "Eye Morse"
    session["room"] = room
    session["server_url"] = server_url or session["server_url"]
    session["role"] = role if role in ("host", "join") else "host"
    return session


def save_session(session: dict, path=None) -> dict:
    stored = default_session()
    stored["name"] = str(session.get("name", stored["name"])).strip()[:40] or "Eye Morse"
    stored["room"] = normalize_room(str(session.get("room", stored["room"])))
    stored["server_url"] = str(session.get("server_url", stored["server_url"])).strip().rstrip("/")
    role = session.get("role", stored["role"])
    stored["role"] = role if role in ("host", "join") else "host"
    if stored["role"] == "join":
        parsed_url, parsed_room = parse_room_link(stored["server_url"])
        stored["server_url"] = parsed_url or default_session()["server_url"]
        if parsed_room:
            stored["room"] = parsed_room
    else:
        stored["server_url"] = lan_url()
    session_path = path or config.ROOM_SESSION_FILE
    session_path.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    return stored


def fetch_messages(
    room: str,
    server_url: str = "http://127.0.0.1:8766",
    timeout_seconds: float = 2.0,
) -> tuple[list, str]:
    """Return ``(messages, error)``. Error is empty when the request worked."""
    room_code = normalize_room(room)
    endpoint = f"{server_url.rstrip('/')}/api/rooms/{room_code}/messages"
    request = urllib.request.Request(endpoint, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return [], f"room server returned HTTP {exc.code}"
    except urllib.error.URLError:
        return [], "room server is unavailable"
    except TimeoutError:
        return [], "room server timed out"
    except (json.JSONDecodeError, UnicodeError):
        return [], "room server returned an unreadable reply"
    except Exception:
        return [], "room server closed the connection"
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return [], "room server returned an unreadable reply"
    return messages, ""


def publish_confirmed_message(
    text: str,
    room: str,
    sender: str = "Eye Morse",
    server_url: str = "http://127.0.0.1:8766",
    timeout_seconds: float = 2.0,
) -> tuple[bool, str]:
    """Post one confirmed message to a local Trusted Text Room.

    Returns:
        (True, "") on success.
        (False, human_readable_error) on failure.
    """
    final_text = text.strip()
    room_code = "".join(char for char in room.upper() if char.isalnum())[:12]

    if not final_text:
        return False, "message is empty"

    if not room_code:
        return False, "room code is empty"

    base_url = server_url.rstrip("/")
    endpoint = f"{base_url}/api/rooms/{room_code}/messages"

    payload = json.dumps(
        {
            "sender": sender.strip()[:40] or "Eye Morse",
            "text": final_text[:500],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            if 200 <= response.status < 300:
                return True, ""

            return False, f"room server returned HTTP {response.status}"

    except urllib.error.HTTPError as exc:
        return False, f"room server returned HTTP {exc.code}"

    except urllib.error.URLError:
        return False, "room server is unavailable"

    except TimeoutError:
        return False, "room server timed out"

    except Exception as exc:
        return False, f"room server closed the connection ({type(exc).__name__})"