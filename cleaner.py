"""Turn raw Morse letters into a readable sentence.

Spaces the blinker already made are kept. A chunk with no space can be split
into words. A spelling change is kept only when it is at least 75% the same as
the letters that were blinked. Less recognizable tokens, including acronyms,
stay as typed. Assist shortcuts do not use this.
"""

from __future__ import annotations

_spell = None
_load_failed = False
_MIN_SIMILARITY = 0.75
# A short token is not rewritten into a rare dictionary word. That keeps
# acronyms such as NASA from becoming an obscure near-match.
_MIN_SHORT_COUNT = 100_000


def _spell_checker():
    global _spell, _load_failed
    if _spell is not None or _load_failed:
        return _spell
    try:
        import importlib.resources

        from symspellpy import SymSpell

        spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
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


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, ca in enumerate(left, 1):
        cur = [i]
        for j, cb in enumerate(right, 1):
            cur.append(min(
                cur[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + (ca != cb),
            ))
        prev = cur
    return prev[-1]


def _similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    dist = _edit_distance(left, right)
    return 1.0 - dist / max(len(left), len(right), 1)


def _known(spell, token: str) -> bool:
    from symspellpy import Verbosity

    return bool(spell.lookup(token, Verbosity.TOP, max_edit_distance=0))


def _max_edits(token: str) -> int:
    """Edits allowed while staying at least 75% the same."""
    return int(len(token) * (1.0 - _MIN_SIMILARITY))


def _close_enough(original: str, suggestion: str, *, protect_short_swap: bool) -> bool:
    """True when a suggestion is a mild typo, not a different short token."""
    if _similarity(original, suggestion) < _MIN_SIMILARITY:
        return False
    dist = _edit_distance(original, suggestion)
    # "nasa" -> "nasal" is a short token glued onto a longer word, not a typo.
    if protect_short_swap and len(original) <= 4 and abs(len(original) - len(suggestion)) == 1:
        if (
            suggestion.startswith(original) or original.startswith(suggestion)
            or suggestion.endswith(original) or original.endswith(suggestion)
        ):
            return False
    # Added or dropped letters only: "helo" -> "hello", "nightt" -> "night".
    if dist == abs(len(original) - len(suggestion)):
        return True
    # A changed letter in a short standalone token is often an acronym ("nasa").
    if protect_short_swap and len(original) < 6:
        return False
    return True


def _correct_token(spell, token: str) -> str:
    """Fix one word, or return it unchanged when the guess is too different."""
    if _known(spell, token):
        return token
    max_dist = _max_edits(token)
    if max_dist < 1:
        return token
    from symspellpy import Verbosity

    suggestions = spell.lookup(token, Verbosity.CLOSEST, max_edit_distance=max_dist)
    best = None
    best_sim = 0.0
    for sug in suggestions:
        sim = _similarity(token, sug.term)
        if len(token) <= 4 and sug.count < _MIN_SHORT_COUNT:
            continue
        if sim > best_sim and _close_enough(token, sug.term, protect_short_swap=True):
            best = sug.term
            best_sim = sim
    return best or token


def _best_span(source: str, cursor: int, word: str) -> tuple[str, int]:
    """Slice of ``source`` that this suggested word most likely came from."""
    rest = source[cursor:]
    if not rest:
        return "", 0
    best_span = rest[:1]
    best_sim = -1.0
    for length in range(1, min(len(rest), len(word) + 2) + 1):
        span = rest[:length]
        sim = _similarity(span, word)
        if sim > best_sim or (sim == best_sim and span == word):
            best_sim = sim
            best_span = span
    return best_span, len(best_span)


def _segment_chunk(spell, letters: str) -> str:
    segmented = spell.word_segmentation(letters, max_edit_distance=1).corrected_string.strip()
    words = segmented.split()
    if len(words) <= 1:
        return _correct_token(spell, letters)
    cursor = 0
    kept = []
    for word in words:
        span, consumed = _best_span(letters, cursor, word)
        if consumed <= 0:
            break
        if _close_enough(span, word, protect_short_swap=False):
            kept.append(word)
        else:
            kept.append(span)
        cursor += consumed
    if cursor < len(letters):
        kept.append(letters[cursor:])
    return " ".join(part for part in kept if part)


def clean_message(raw_text: str) -> str:
    """Preview a sentence from Morse text. Empty input stays empty."""
    if not raw_text or not raw_text.strip():
        return ""
    spell = _spell_checker()
    parts = []
    for chunk in raw_text.split():
        letters = "".join(ch for ch in chunk.lower() if ch.isalpha())
        if not letters:
            continue
        if spell is None:
            parts.append(letters)
            continue
        if len(letters) > 6 and not _known(spell, letters):
            parts.append(_segment_chunk(spell, letters))
        else:
            parts.append(_correct_token(spell, letters))
    return " ".join(parts).upper()
