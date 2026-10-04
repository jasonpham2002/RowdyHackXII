"""Turn raw Morse letters into a readable sentence.

Spaces the blinker already made are kept. A chunk with no space is segmented
into words, so a fast blinker who never paused still gets word breaks. Assist
shortcuts do not use this. The cleaned line is a preview until the user sends.
"""

from __future__ import annotations

_spell = None
_load_failed = False


def _spell_checker():
    global _spell, _load_failed
    if _spell is not None or _load_failed:
        return _spell
    try:
        import importlib.resources

        from symspellpy import SymSpell

        # Distance 1 fixes a missed letter without turning "helpim" into "helping".
        spell = SymSpell(max_dictionary_edit_distance=1, prefix_length=7)
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
        segmented = spell.word_segmentation(letters).corrected_string.strip()
        parts.append(segmented or letters)
    return " ".join(parts).upper()
