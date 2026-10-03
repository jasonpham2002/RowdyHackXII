"""International Morse code table and decoding helpers."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# Dot/dash sequence -> character (letters, digits, a few punctuation marks).
MORSE_TO_CHAR: Dict[str, str] = {
    ".-": "A",    "-...": "B",  "-.-.": "C", "-..": "D",   ".": "E",
    "..-.": "F",  "--.": "G",   "....": "H", "..": "I",    ".---": "J",
    "-.-": "K",   ".-..": "L",  "--": "M",   "-.": "N",    "---": "O",
    ".--.": "P",  "--.-": "Q",  ".-.": "R",  "...": "S",   "-": "T",
    "..-": "U",   "...-": "V",  ".--": "W",  "-..-": "X",  "-.--": "Y",
    "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
    ".-.-.-": ".", "--..--": ",", "..--..": "?", "-..-.": "/",
    "-....-": "-", ".----.": "'", "-.-.--": "!", ".--.-.": "@",
}

CHAR_TO_MORSE: Dict[str, str] = {v: k for k, v in MORSE_TO_CHAR.items()}


def decode(symbols: str) -> Optional[str]:
    """Decode a dot/dash string (e.g. ``'.-'``) into a character.

    Returns ``None`` for an unknown sequence so the caller can flash an error.
    """
    if not symbols:
        return None
    return MORSE_TO_CHAR.get(symbols)


def encode(char: str) -> Optional[str]:
    """Return the dot/dash string for a character (used for the HUD chart)."""
    return CHAR_TO_MORSE.get(char.upper())


def reference_rows() -> List[Tuple[str, str]]:
    """Sorted (char, morse) pairs for A-Z then 0-9, for the on-screen chart."""
    order = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    order += [str(d) for d in range(10)]
    return [(ch, CHAR_TO_MORSE[ch]) for ch in order if ch in CHAR_TO_MORSE]
