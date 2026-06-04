"""Multilingual filler word / phrase lists.

Single source of truth for filler detection. Used by:
  - services/stress_snippet_service._count_fillers (candidate generation)
  - utils/metrics.count_fillers (callers can pass get_filler_list(lang))

Each list contains lowercase tokens. Multi-word fillers ("you know", "i mean")
are matched as whole phrases by callers; single-word fillers as whole words.
Lists prioritize high-frequency disfluencies over edge cases. Easy to extend.

Sources: linguistics literature on cross-language disfluency, Wiktionary,
conversational-speech corpora.

Adding a language: append the ISO 639-1 code and its list below. Callers
auto-pick up new languages via `get_filler_list`.
"""
from __future__ import annotations

from typing import Optional

# Default language when nothing is known.
DEFAULT_LANGUAGE = "en"

FILLER_LISTS: dict[str, list[str]] = {
    "en": [
        "um", "uh", "erm", "hmm",
        "like", "you know", "i mean",
        "sort of", "kind of",
        "basically", "literally", "actually",
        "right", "so",
    ],
    "pl": [
        # Polish — disfluencies + common discourse particles used as fillers.
        "yyy", "eee", "yy", "ee",
        "no", "yyyy",
        "wiesz", "wiesz co",
        "znaczy", "znaczy się",
        "tak naprawdę", "po prostu",
        "tego", "tak jakby",
        "jakby", "nie",
    ],
    "es": [
        # Spanish.
        "eh", "este", "esto",
        "pues", "bueno",
        "o sea", "vale",
        "digamos", "como",
        "a ver", "es que",
    ],
    "de": [
        # German.
        "äh", "ähm", "öh",
        "also", "halt",
        "eben", "ja", "naja",
        "sozusagen", "irgendwie",
        "quasi",
    ],
}


def get_filler_list(language: Optional[str]) -> list[str]:
    """Return the filler list for ``language`` (ISO 639-1).

    Falls back to English when ``language`` is None, empty, or unknown.
    Case-insensitive lookup. Always returns a non-empty list.
    """
    if not language:
        return FILLER_LISTS[DEFAULT_LANGUAGE]
    code = language.strip().lower()[:2]  # accept "en-US" etc.
    return FILLER_LISTS.get(code, FILLER_LISTS[DEFAULT_LANGUAGE])


def supported_languages() -> list[str]:
    """ISO 639-1 codes this module has filler lists for."""
    return sorted(FILLER_LISTS.keys())
