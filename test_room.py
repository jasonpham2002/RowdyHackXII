"""Room link parsing and saved session. No camera required."""

import tempfile
from pathlib import Path

from chat_client import load_session, parse_room_link, save_session


def test_join_link_sets_server_and_room():
    server, room = parse_room_link("http://10.188.29.234:8766/?room=ROWDY1")
    assert server == "http://10.188.29.234:8766"
    assert room == "ROWDY1"


def test_join_saves_the_other_laptop():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "room_session.json"
        saved = save_session({
            "name": "Friend",
            "room": "ignored",
            "role": "join",
            "server_url": "http://10.188.29.234:8766/?room=ROWDY1",
        }, path)
        assert saved["name"] == "Friend"
        assert saved["room"] == "ROWDY1"
        assert saved["server_url"] == "http://10.188.29.234:8766"
        assert load_session(path)["role"] == "join"


def test_join_without_a_link_keeps_a_blank_server_out():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "room_session.json"
        saved = save_session({
            "name": "Friend",
            "room": "ROWDY1",
            "role": "join",
            "server_url": "",
        }, path)
        assert saved["room"] == "ROWDY1"
        assert saved["server_url"].startswith("http://")


def test_room_page_uses_the_briefing_pattern():
    from chat_server import app

    client = app.test_client()
    page = client.get("/").get_data(as_text=True)
    assert "Operation Morse" in page
    assert "Host this room" in page
    assert "Join a room" in page
    assert "Cinzel" in page
    font = client.get("/fonts/cinzel-latin.woff2")
    assert font.status_code == 200
    assert client.get("/fonts/not-a-font.woff2").status_code == 404


if __name__ == "__main__":
    test_join_link_sets_server_and_room()
    test_join_saves_the_other_laptop()
    test_join_without_a_link_keeps_a_blank_server_out()
    test_room_page_uses_the_briefing_pattern()
    print("room tests passed")
