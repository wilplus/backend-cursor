"""Named emotion on the take (F2 handoff §2, 2026-08-03).

The pre-recording emotion-naming exercise's answer used to evaporate.
Captured now as `named_emotion` on the take's intake_context: a KEY from
the closed vocabulary below (the FE sends the key; display text lives FE-
side pending founder sign-off of the exact 10 words — the keys and their
buckets are stable regardless).

The coach SEES the named emotion (founder-decided: it is the user's own
self-report, not a machine guess — the blind-coach fence bans model
output, not the student's voice).

CONSTRUCT FENCE — the threat/challenge BUCKET mapping below is INTERNAL
ONLY: it exists for the drift metric's log line and must never ride any
user- or coach-facing payload. Serialize the key, never the bucket.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The closed vocabulary — keys only; store the key, not display text.
CHALLENGE_KEYS = ("calm", "curious", "excited", "determined", "confident")
THREAT_KEYS = ("nervous", "tense", "overwhelmed", "doubtful")
NEUTRAL_KEYS = ("tired",)
EMOTION_KEYS = frozenset(CHALLENGE_KEYS + THREAT_KEYS + NEUTRAL_KEYS)

# INTERNAL analytics bucket per key (CONSTRUCT — log-only, never wire).
_BUCKETS = {
    **{k: "challenge" for k in CHALLENGE_KEYS},
    **{k: "threat" for k in THREAT_KEYS},
    **{k: "neutral" for k in NEUTRAL_KEYS},
}


def normalize_named_emotion(value: Any) -> Optional[str]:
    """The validated vocabulary key, or None. Case/padding tolerant; an
    unknown word is DROPPED (never stored, never blocks the recording)."""
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    return key if key in EMOTION_KEYS else None


def log_drift_signal(user_id: Any, session_id: Any, key: str) -> None:
    """One log line per captured emotion — the F2 drift metric's raw
    stream (per user, rolling share of threat-flavored picks over
    sessions is computed OFF-SURFACE from these). Log-only: the bucket
    never persists to a row and never reaches a payload (CONSTRUCT)."""
    bucket = _BUCKETS.get(key)
    if not bucket:
        return
    logger.info("named_emotion.captured user=%s session=%s emotion=%s "
                "bucket=%s", user_id, session_id, key, bucket)
