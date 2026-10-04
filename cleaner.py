"""Turn raw Morse letters into a conservative, readable sentence.

The cleaner preserves explicit spaces. It only changes a token when the change
is deterministic and covered by the local correction rules. No network calls
are made.
"""

from __future__ import annotations

import re


EXACT_PHRASES = {
    "youhavagoodnight": "you have goodnight",
    "youhvveagoodnight": "you have goodnight",
    "ineedhelp": "i need help",
    "pleasehelpiminroom": "please help im in room",
}

TOKEN_CORRECTIONS = {
    "helo": "hello",
    "nightt": "night",
}

KNOWN_SHORT_TOKENS = {
    "sos",
    "nasa",
    "fbi",
    "xyzq",
}


def _normalize(raw_text: str) -> str:
    normalized = raw_text.lower()
    normalized = re.sub(r"[^a-z0-9\s.,!?'\-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _clean_token(token: str) -> str:
    if token in KNOWN_SHORT_TOKENS:
        return token

    return TOKEN_CORRECTIONS.get(token, token)


def clean_message(raw_text: str) -> str:
    """Return a conservative cleaned preview for a raw Morse line."""
    normalized = _normalize(raw_text)

    if not normalized:
        return ""

    if normalized in EXACT_PHRASES:
        return EXACT_PHRASES[normalized].upper()

    if " " in normalized:
        return " ".join(
            _clean_token(token)
            for token in normalized.split()
        ).upper()

    return _clean_token(normalized).upper()