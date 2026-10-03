"""Word prediction to cut the number of blinks needed per word.

Builds a frequency-ranked English vocabulary once (via ``wordfreq``) and returns
the most common completions for the current prefix. Falls back to a small built
in list if ``wordfreq`` is unavailable, so the app still runs.
"""

from __future__ import annotations

from typing import List

import config

_FALLBACK_WORDS = [
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
    "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
    "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
    "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "hello", "world", "yes", "no", "please", "thanks", "help", "morse",
    "code", "eye", "blink", "name", "water", "food", "stop", "go",
]


class WordPredictor:
    def __init__(self) -> None:
        self._vocab: List[str] = self._load_vocab()

    @staticmethod
    def _load_vocab() -> List[str]:
        try:
            from wordfreq import top_n_list

            words = top_n_list("en", config.VOCAB_SIZE)
            # Keep alphabetic words only; preserve frequency order.
            return [w for w in words if w.isalpha()]
        except Exception:
            return list(_FALLBACK_WORDS)

    def predict(self, prefix: str, n: int = config.NUM_SUGGESTIONS) -> List[str]:
        """Top-``n`` completions for ``prefix`` (already frequency-ordered)."""
        prefix = prefix.lower()
        if not prefix:
            return []
        out: List[str] = []
        for word in self._vocab:
            if word.startswith(prefix) and word != prefix:
                out.append(word)
                if len(out) >= n:
                    break
        return out
