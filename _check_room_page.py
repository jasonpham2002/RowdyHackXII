"""Throwaway check for the room page markup. Does not save a session."""

from chat_server import app

client = app.test_client()
page = client.get("/")
body = page.data.decode()
assert page.status_code == 200, page.status_code
for needle in (
    "Host this room",
    "Join a room",
    "Open a room",
    "Operation Morse",
    'id="name"',
    'id="room"',
    'id="link"',
    'id="share"',
    'id="messages"',
):
    assert needle in body, needle
font = client.get("/fonts/cinzel-latin.woff2")
print("page", page.status_code, "font", font.status_code, len(font.data))
