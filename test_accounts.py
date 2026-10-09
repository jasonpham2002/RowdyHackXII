"""Account login and stored room messages. Requires PostgreSQL."""

import uuid

from chat_server import app
import db


def _remove(email: str, room: str) -> None:
    try:
        with db._query_lock:
            conn = db._connect_locked()
            conn.execute("DELETE FROM messages WHERE room = %s", (room,))
            conn.execute(
                "DELETE FROM messages WHERE user_id IN (SELECT id FROM users WHERE email = %s)",
                (email,),
            )
            conn.execute("DELETE FROM users WHERE email = %s", (email,))
    except db.DatabaseUnavailable:
        pass


def test_messages_require_login():
    client = app.test_client()
    denied = client.get("/api/rooms/ROWDY1/messages")
    assert denied.status_code == 401
    assert "Log in" in denied.get_json()["error"]
    empty = client.post("/api/rooms/ROWDY1/messages", json={"text": "hello"})
    assert empty.status_code == 401


def test_register_login_message_and_logout():
    email = f"acct-{uuid.uuid4().hex}@example.com"
    room = "T" + uuid.uuid4().hex[:6].upper()
    password = "correct-horse"
    client = app.test_client()
    try:
        short = client.post("/api/register", json={
            "email": email,
            "password": "short",
            "displayName": "Minh",
        })
        assert short.status_code == 400

        created = client.post("/api/register", json={
            "email": email,
            "password": password,
            "displayName": "Minh Le",
        })
        assert created.status_code == 201
        created_body = created.get_json()
        assert created_body["user"]["email"] == email
        assert created_body["user"]["displayName"] == "Minh Le"
        assert "password" not in created_body["user"]
        token = created_body["token"]
        assert token

        duplicate = client.post("/api/register", json={
            "email": email.upper(),
            "password": password,
            "displayName": "Minh Le",
        })
        assert duplicate.status_code == 409

        wrong = client.post("/api/login", json={"email": email, "password": "wrong-password"})
        assert wrong.status_code == 401

        signed_in = client.post("/api/login", json={"email": email, "password": password})
        assert signed_in.status_code == 200
        token = signed_in.get_json()["token"]
        bearer = {"Authorization": f"Bearer {token}"}

        posted = client.post(
            f"/api/rooms/{room}/messages",
            json={"text": "hello from the test", "sender": "Impersonator"},
            headers=bearer,
        )
        assert posted.status_code == 201
        message = posted.get_json()["message"]
        assert message["sender"] == "Minh Le"
        assert message["text"] == "hello from the test"
        assert message["sentAt"]

        listed = client.get(f"/api/rooms/{room}/messages", headers=bearer)
        assert listed.status_code == 200
        assert listed.get_json()["messages"][-1]["id"] == message["id"]

        cookie_client = app.test_client()
        cookie_client.post("/api/login", json={"email": email, "password": password})
        from_cookie = cookie_client.get(f"/api/rooms/{room}/messages")
        assert from_cookie.status_code == 200

        me = client.get("/api/me", headers=bearer)
        assert me.status_code == 200
        assert me.get_json()["user"]["displayName"] == "Minh Le"

        logged_out = client.post("/api/logout", headers=bearer)
        assert logged_out.status_code == 200
        assert client.get(f"/api/rooms/{room}/messages", headers=bearer).status_code == 401
        assert client.post(
            f"/api/rooms/{room}/messages",
            json={"text": "after logout"},
            headers=bearer,
        ).status_code == 401
    finally:
        _remove(email, room)


if __name__ == "__main__":
    test_messages_require_login()
    test_register_login_message_and_logout()
    print("account tests passed")
