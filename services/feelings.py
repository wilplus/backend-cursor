"""Pre-recording feeling — the closed taxonomy (willab U10).

Mirrors the FE's ``willabFeelings.ts`` enum EXACTLY (src/components/willab/) so
the BE accepts precisely what the capture UI sends; anything else is dropped (we
never coerce an unknown state into a known one). The DB CHECK constraint in
migrations/add_recording_feelings.sql is the matching SQL-side guard.

AC-9: this is the user naming their OWN state — never a score or verdict. It is
stored privately and factored only at the audit stage (felt-state × performance).
"""
from __future__ import annotations

from typing import Any, Optional

# Exact mirror of FE `type Feeling` — keep in lock-step.
VALID_FEELINGS = ("nervous", "excited", "calm", "unsure")


def normalize_feeling(raw: Any) -> Optional[str]:
    """Return a valid feeling (lower-cased, trimmed) or None. None means
    'not provided / not recognised' — the caller stores nothing (the take is
    still recorded; the feeling is purely additive)."""
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    return v if v in VALID_FEELINGS else None
