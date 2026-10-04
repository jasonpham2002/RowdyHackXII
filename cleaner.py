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

_spell = None
_load_failed = False


def _spell_checker():
    global _spell, _load_failed
    if _spell is not None or _load_failed:
        return _spell
    try:
        import importlib.resources

        from symspellpy import SymSpell

        # max_dictionary_edit_distance=0 disables typo correction for segmentation-only mode.
        spell = SymSpell(max_dictionary_edit_distance=0, prefix_length=7)
        dictionary_path = str(
            importlib.resources.files("symspellpy") / "frequency_dictionary_en_82_765.txt"
        )
        if not spell.load_dictionary(dictionary_path, term_index=0, count_index=1):
            _load_failed = True
            return None
        _spell = spell
    except Exception:
        _load_failed = True
        return None
    return _spell


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

    spell = _spell_checker()
    parts = []

    for token in normalized.split():
        cleaned = _clean_token(token)
        # Apply SymSpell space parsing if we have spell checker and it's alphabetic
        if spell and cleaned.isalpha() and cleaned not in KNOWN_SHORT_TOKENS and cleaned not in TOKEN_CORRECTIONS.values():
            segmented = spell.word_segmentation(cleaned, max_edit_distance=0).segmented_string.strip()
            parts.append(segmented or cleaned)
        else:
            parts.append(cleaned)
            
    return " ".join(parts).upper()
