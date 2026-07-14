"""Pre-take mindset-priming manipulation — the closed condition taxonomy
(willab, founder 2026-07-13).

The FE shows one framing panel before each live take (threat → take 1,
challenge → take 2, balanced → take 3; one phrase picked at random from that
take's set) and reports which condition + phrase the take saw. The BE logs it
per take so the framing manipulation can be correlated against the acoustic
read (pitch / rate / pauses / power).

AC-9 / split-sink: this is a PRIVATE research label, never a score or verdict
shown back to the user. It is stored on the take's session row (see
migrations/add_session_priming.sql) and surfaced to the COACH review only —
never the readout, the instant view, or the student batch view. The phrase may
reference "grading/score" as a priming device; that is intentional framing, not
a derived analysis number, so it does not touch the AC-9 "no numbers to users"
rule (it is never displayed as analysis output).
"""
from __future__ import annotations

from typing import Any, Optional

# The three framing conditions (one per batch position). Keep in lock-step with
# the FE's priming panel.
VALID_PRIMING_CONDITIONS = ("threat", "challenge", "balanced")

# Defensive cap — the phrase is free text shown to the user, stored verbatim.
_MAX_PHRASE_CHARS = 500


def normalize_priming_condition(raw: Any) -> Optional[str]:
    """Return a valid condition (lower-cased, trimmed) or None. None means
    'not provided / not recognised' — the caller stores nothing (the take is
    still recorded; the priming label is purely additive). An unknown value is
    DROPPED, never coerced into a known condition."""
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    return v if v in VALID_PRIMING_CONDITIONS else None


def normalize_priming_phrase(raw: Any) -> Optional[str]:
    """Return the trimmed phrase verbatim (capped at _MAX_PHRASE_CHARS) or
    None. Free text — stored as shown; only trimmed + length-bounded."""
    if not isinstance(raw, str):
        return None
    v = raw.strip()
    if not v:
        return None
    return v[:_MAX_PHRASE_CHARS]
