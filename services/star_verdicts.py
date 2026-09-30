"""Coach star verdicts (founder 2026-07-27) — the DECISION-layer correction
corpus for the voice-text analytics.

WHY THIS EXISTS. The coach can already correct what a star SAYS: the
(ai_draft, coach_final) pairs on comments and say-it-stronger cards ride
admin_annotation_events into the DPO/fine-tune exports. Nothing could correct
whether a star should have FIRED. A preference pair over two strings teaches a
generator to write better copy; it can never teach a detector to stay quiet.

So: one coach judgment per fired star.

    keep              the trigger was right (the endorsement signal — mirrors
                      'approved_as_is' on the prose side)
    wrong_kind        a star belonged here, but not this one; ``corrected_device``
                      carries what it should have been (a labeled confusion pair)
    should_not_fire   the trigger was wrong; this moment deserved silence

FENCES.
  * BLIND COACH — THE live fence for this module. This surface deliberately
    shows the coach the machine's guess and asks them to judge it. That is safe
    here (a star is not a confidence label) and unsafe anywhere near the
    labeling lane, so: a separate endpoint from the blind labeling surface, and
    this corpus is NEVER joined into the user-facing feedback or confidence
    lanes. The module is pinned by tests so a future edit cannot quietly cross
    that wall.
  * AC-9 — a verdict is coach->machine only. Nothing here is ever surfaced back
    to the student.
  * L1 — a verdict never mutates text. It judges a star; the student's copy is
    untouched.

KNOWN GAP, DELIBERATE: false NEGATIVES are not captured. A star that should
have fired and didn't leaves no row, because there is no object to judge. That
needs its own surface and was scoped out. ``corpus_summary`` reports this in
every pull so a training run cannot mistake this for a balanced sample.

Pure — validation, vocabulary, and corpus shaping only. No DB, no LLM.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

VERDICTS = ("keep", "wrong_kind", "should_not_fire")

# The star families, mirroring moment_suggestions.kind (the CHECK in
# alter_moment_suggestions_kind_delivery.sql). A verdict on a kind this table
# doesn't know is rejected rather than stored — an unknown kind means the star
# vocabulary moved and this module wasn't updated.
STAR_KINDS = ("emphasize", "replace", "structure", "delivery")

_MAX_NOTE_LEN = 1000


_USER_SUPPRESS_VERDICTS = ("wrong_kind", "should_not_fire")
_RETIRED_SIGNAL_TRIGGERS = {"challenge", "threat", "breakthrough"}


def _uses_retired_signal(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and str(row.get("trigger") or "").strip().lower()
        in _RETIRED_SIGNAL_TRIGGERS
    )


def released_user_verdicts(verdicts: Any, pieces: Any,
                            sessions: Any) -> dict:
    """Coach verdicts released for the student surface after publish only."""
    rows = verdicts if isinstance(verdicts, dict) else {}
    published = {
        str(session.get("id")) for session in (sessions or [])
        if isinstance(session, dict) and session.get("id")
        and session.get("results_published_at")
    }
    snippet_sessions = {
        str(piece.get("snippet_id")): str(piece.get("take_session_id"))
        for piece in (pieces or []) if isinstance(piece, dict)
        and piece.get("snippet_id") and piece.get("take_session_id")
    }
    return {
        str(snippet_id): row for snippet_id, row in rows.items()
        if snippet_sessions.get(str(snippet_id)) in published
    }


def filter_user_suggestions(suggestions: Any, verdicts: Any) -> dict:
    """Suppress coach-rejected pending machine feedback on the user surface.

    Already accepted words are protected by the ledger; a coach correction or
    retraction is emitted separately as a fresh proposal.
    """
    rows = suggestions if isinstance(suggestions, dict) else {}
    judged = verdicts if isinstance(verdicts, dict) else {}
    return {
        str(sid): row for sid, row in rows.items()
        if (judged.get(str(sid)) or {}).get("verdict")
        not in _USER_SUPPRESS_VERDICTS
        and not _uses_retired_signal(row)
    }


# The ONLY snippet fields that may ride the coach review list — playback +
# context, requested by the FE (2026-07-28). An allowlist on purpose: the
# snippet row also carries metrics (acoustic_read, voice_confidence,
# user_tone_word…), and passing it through wholesale would put the machine's
# voice-read on the same screen as an analytics review (BLIND COACH).
_SNIPPET_PLAYBACK_KEYS = (
    "audio_ref", "start_offset_ms", "duration_ms", "transcript", "take_index",
)


_STAR_TEXT_KEYS = ("kind", "trigger", "why", "replacement_text")


