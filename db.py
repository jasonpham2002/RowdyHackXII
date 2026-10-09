"""PostgreSQL accounts and confirmed room messages.

Set DATABASE_URL in a local .env file. Camera frames, landmarks, calibration,
and unfinished Morse drafts are never written here.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
from pathlib import Path

from psycopg import connect
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash


class DatabaseUnavailable(Exception):
    """PostgreSQL is missing, stopped, or rejected the connection."""


class DuplicateEmail(Exception):
    """An account with this email already exists."""


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT UNIQUE NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id BIGSERIAL PRIMARY KEY,
        room TEXT NOT NULL,
        user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
        sender TEXT NOT NULL,
        body TEXT NOT NULL,
        sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS messages_room_sent_at_idx
    ON messages (room, sent_at)
    """,
)

_query_lock = threading.Lock()
_conn = None


def load_local_env() -> None:
    """Load KEY=VALUE lines from .env without overriding existing variables."""
    path = Path(__file__).resolve().with_name(".env")
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def init_db() -> None:
    with _query_lock:
        _connect_locked()


def normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or email.count("@") != 1 or any(char.isspace() for char in email):
        raise ValueError("Enter a valid email address.")
    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Enter a valid email address.")
    return email


def validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8 or len(password) > 200:
        raise ValueError("Use a password between 8 and 200 characters.")
    return password


def validate_display_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 40:
        raise ValueError("Enter a display name up to 40 characters.")
    return name


def public_user(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "display_name": row["display_name"],
    }


def public_message(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "sender": row["sender"],
        "text": row["body"],
        "sentAt": row["sent_at"].isoformat(),
    }


def create_user(email: str, password: str, display_name: str) -> dict:
    normalized = normalize_email(email)
    secret = validate_password(password)
    name = validate_display_name(display_name)
    password_hash = generate_password_hash(secret)
    try:
        row = _run(
            lambda conn: conn.execute(
                """
                INSERT INTO users (email, password_hash, display_name)
                VALUES (%s, %s, %s)
                RETURNING id, email, display_name
                """,
                (normalized, password_hash, name),
            ).fetchone()
        )
    except UniqueViolation:
        raise DuplicateEmail from None
    if row is None:
        raise DatabaseUnavailable("PostgreSQL did not save the account.")
    return public_user(row)


def authenticate(email: str, password: str) -> dict | None:
    try:
        normalized = normalize_email(email)
    except ValueError:
        return None
    if not isinstance(password, str) or not password:
        return None
    row = _run(
        lambda conn: conn.execute(
            """
            SELECT id, email, display_name, password_hash
            FROM users
            WHERE email = %s
            """,
            (normalized,),
        ).fetchone()
    )
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return public_user(row)


def issue_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    digest = _token_hash(token)
    _run(
        lambda conn: conn.execute(
            "INSERT INTO api_tokens (user_id, token_hash) VALUES (%s, %s)",
            (user_id, digest),
        )
    )
    return token


def user_from_token(token: str) -> dict | None:
    cleaned = str(token or "").strip()
    if not cleaned or len(cleaned) > 128:
        return None
    row = _run(
        lambda conn: conn.execute(
            """
            SELECT users.id, users.email, users.display_name
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.token_hash = %s
            """,
            (_token_hash(cleaned),),
        ).fetchone()
    )
    if row is None:
        return None
    return public_user(row)


def revoke_token(token: str) -> None:
    cleaned = str(token or "").strip()
    if not cleaned:
        return
    _run(
        lambda conn: conn.execute(
            "DELETE FROM api_tokens WHERE token_hash = %s",
            (_token_hash(cleaned),),
        )
    )


def get_user(user_id: int) -> dict | None:
    row = _run(
        lambda conn: conn.execute(
            "SELECT id, email, display_name FROM users WHERE id = %s",
            (int(user_id),),
        ).fetchone()
    )
    if row is None:
        return None
    return public_user(row)


def insert_message(room: str, user_id: int, sender: str, text: str) -> dict:
    body = text.strip()[:500]
    if not body:
        raise ValueError("text is required")
    name = (sender or "Eye Morse").strip()[:40] or "Eye Morse"
    row = _run(
        lambda conn: conn.execute(
            """
            INSERT INTO messages (room, user_id, sender, body)
            VALUES (%s, %s, %s, %s)
            RETURNING id, sender, body, sent_at
            """,
            (room, int(user_id), name, body),
        ).fetchone()
    )
    if row is None:
        raise DatabaseUnavailable("PostgreSQL did not save the message.")
    return public_message(row)


def list_messages(room: str, limit: int = 100) -> list[dict]:
    capped = max(1, min(int(limit), 100))
    rows = _run(
        lambda conn: conn.execute(
            """
            SELECT id, sender, body, sent_at
            FROM (
                SELECT id, sender, body, sent_at
                FROM messages
                WHERE room = %s
                ORDER BY sent_at DESC, id DESC
                LIMIT %s
            ) AS recent
            ORDER BY sent_at ASC, id ASC
            """,
            (room, capped),
        ).fetchall()
    )
    return [public_message(row) for row in rows]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _run(fn):
    with _query_lock:
        try:
            return _call_locked(fn)
        except (DatabaseUnavailable, DuplicateEmail, UniqueViolation, ValueError):
            raise
        except Exception:
            _reset_locked()
            try:
                return _call_locked(fn)
            except (DatabaseUnavailable, DuplicateEmail, UniqueViolation, ValueError):
                raise
            except Exception as exc:
                _reset_locked()
                print(f"[room] database query failed ({type(exc).__name__})")
                raise DatabaseUnavailable(
                    "PostgreSQL is unavailable. Start the database and check DATABASE_URL."
                ) from exc


def _call_locked(fn):
    """Run one query. Caller must hold ``_query_lock``."""
    conn = _connect_locked()
    return fn(conn)


def _connect_locked():
    """Open the shared connection. Caller must hold ``_query_lock``."""
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseUnavailable(
            "PostgreSQL is not configured. Set DATABASE_URL and start the database."
        )
    try:
        _conn = connect(
            url,
            autocommit=True,
            connect_timeout=3,
            row_factory=dict_row,
        )
        for statement in _SCHEMA:
            _conn.execute(statement)
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        _reset_locked()
        print(f"[room] database unavailable ({type(exc).__name__})")
        raise DatabaseUnavailable(
            "PostgreSQL is unavailable. Start the database and check DATABASE_URL."
        ) from exc
    return _conn


def _reset_locked() -> None:
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None


load_local_env()
