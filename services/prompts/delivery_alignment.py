"""Prompt for the congruence delivery star (founder 2026-07-24 sign-off).

Moved verbatim from services/delivery_alignment.py (registry extraction
2026-08-03). One binary judgment: are the words clearly positive? The
star copy lives FE-side; this returns only {"words_positive": bool}.
"""
from __future__ import annotations

SYSTEM = (
    "You judge ONE thing for a speaker reviewing their own recording: are the "
    "WORDS of this moment clearly upbeat / positive in meaning? Not neutral, "
    "not negative — clearly positive.\n\n"
    'Return JSON only: {"words_positive": true|false}. Judge the meaning of '
    "the words alone. Do not explain."
)


def user(transcript: str) -> str:
    return f'The words for this moment:\n"{(transcript or "").strip()}"'


REGISTER = {
    "delivery_alignment.system": SYSTEM,
    "delivery_alignment.user": user,
}
