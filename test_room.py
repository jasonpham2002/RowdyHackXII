"""Room link parsing and saved session. No camera required."""

import tempfile
from pathlib import Path

import secrets

from chat_client import clean_token, load_session, parse_room_link, save_session


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


def test_session_keeps_api_token():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "room_session.json"
        token = secrets.token_urlsafe(32)
        saved = save_session({
            "name": "Gail",
            "room": "ROWDY1",
            "role": "host",
            "token": token,
        }, path)
        assert saved["token"] == token
        assert load_session(path)["token"] == token
        kept = save_session({
            "name": "Gail",
            "room": "ROWDY1",
            "role": "host",
        }, path)
        assert kept["token"] == token
        cleared = save_session({
            "name": "Gail",
            "room": "ROWDY1",
            "role": "host",
            "token": "",
        }, path)
        assert cleared["token"] == ""


def test_clean_token_keeps_urlsafe_tokens():
    token = secrets.token_urlsafe(32)
    assert clean_token(token) == token
    assert clean_token("not a token") == ""


def test_room_page_uses_the_briefing_pattern():
    from chat_server import app

    client = app.test_client()
    page = client.get("/").get_data(as_text=True)
    assert "Operation Morse" in page
    assert "Create account" in page
    assert "Log in" in page
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
    test_session_keeps_api_token()
    test_clean_token_keeps_urlsafe_tokens()
    test_room_page_uses_the_briefing_pattern()
    print("room tests passed")
