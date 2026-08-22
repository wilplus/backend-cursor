"""Named emotion on the take.

The pre-recording emotion-naming exercise's answer used to evaporate.
Captured now as `named_emotion` on the take's intake_context: a KEY from
the closed vocabulary below (the FE sends the key; display text lives
FE-side).

`unsure` is in the vocabulary so the check-in's "Not sure" answer is
preserved rather than discarded.

The coach SEES the named emotion (founder-decided: it is the user's own
self-report, not a machine guess — the blind-coach fence bans model
output, not the student's voice).

The answer is stored verbatim as a validated self-report. It is not converted
to a psychological state, score, direction, or training label.
"""
from __future__ import annotations

from typing import Any, Optional

# The closed vocabulary — keys only; store the key, not display text.
EMOTION_KEYS = frozenset({
    "calm", "curious", "excited", "determined", "confident",
    "nervous", "tense", "overwhelmed", "doubtful", "tired", "unsure",
})


def normalize_named_emotion(value: Any) -> Optional[str]:
    """The validated vocabulary key, or None. Case/padding tolerant; an
    unknown word is DROPPED (never stored, never blocks the recording)."""
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    return key if key in EMOTION_KEYS else None
