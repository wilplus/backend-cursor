"""Deterministic text flags (founder 2026-07-18) — currently one: English
profanity, a REPLACE trigger for the star suggestions. Whole-word,
case-insensitive, no leetspeak heuristics (v1 keeps false positives at zero:
'class', 'assess', 'Scunthorpe' never match). English-only by founder
decision 2026-07-18; other languages are a later pass."""
from __future__ import annotations

import re
from typing import Any

# Deliberately modest: common strong profanity only. Additive — extend the
# tuple, never get clever with substrings.
_PROFANITY = (
    "fuck", "fucking", "fucked", "fucker", "motherfucker",
    "shit", "shitty", "bullshit",
    "asshole", "arsehole",
    "bitch", "bastard",
    "cunt", "dick", "dickhead", "prick",
    "piss", "pissed",
    "damn", "goddamn", "goddammit", "dammit",
    "crap", "crappy",
)

_PROFANITY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _PROFANITY) + r")\b",
    re.IGNORECASE,
)


def has_profanity(text: Any) -> bool:
    """True when the text contains an English profanity (whole word,
    case-insensitive). Pure; False on non-string."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_PROFANITY_RE.search(text))


def find_profanity(text: Any):
    """Character offset of the FIRST profanity hit, or None. Same matcher
    as has_profanity — the quote-narrowing pass (founder 2026-07-20) uses
    it to underline only the carrying sentence. Pure."""
    if not isinstance(text, str) or not text:
        return None
    m = _PROFANITY_RE.search(text)
    return m.start() if m else None
