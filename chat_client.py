"""Local HTTP publisher for the Trusted Text Room demo.

Only explicitly confirmed final text is posted to the local room server.
No camera frames, landmarks, calibration data, raw blink events, or unfinished
Morse drafts are transmitted.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


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