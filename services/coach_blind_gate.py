"""Blind-label-first gate for the contextual coach-review surface.

Confidence is judged from the evidence piece before slide context, machine
analytics, or user-facing authoring controls become available.  The gate is
scoped to the authenticated coach's own ratings: another coach's answer can
never unlock context for the current rater.
"""
from __future__ import annotations

from typing import Any


_RATING_VALUES = (
    "yes", "in_between", "no", "not_sure", "audio_unclear",
    # Historical v1 rows remain valid completed labels.
    "neutral",
)


def has_committed_blind_label(coach_state: Any) -> bool:
    """Whether this coach committed a real answer or explicit abstention."""
    if not isinstance(coach_state, dict):
        return False
    return (
        coach_state.get("rating_value") in _RATING_VALUES
        or coach_state.get("rating_unrateable") is True
    )


def blind_label_progress(snippets: Any) -> dict:
    """Return the session-level blind-pass state for shaped snippet rows."""
    rows = [row for row in (snippets or []) if isinstance(row, dict)]
    labelled = sum(
        1 for row in rows
        if has_committed_blind_label(row.get("coach_state"))
    )
    total = len(rows)
    return {
        "labelled": labelled,
        "total": total,
        "complete": total == 0 or labelled == total,
    }


def reveal_transcript_after_commit(transcript: Any, *, committed: bool) -> str:
    """Return exact words only after this rater has saved a blind answer.

    This is shared by the contextual coach packet and the imported-corpus
    queue.  Keeping the rule server-side means an unlabeled transcript is not
    merely hidden by CSS or recoverable from the browser's network payload.
    """
    if not committed:
        return ""
    return transcript if isinstance(transcript, str) else ""


def redact_contextual_snippets(snippets: Any) -> list[dict]:
    """Allowlist the blind evidence packet while the pass is incomplete.

    The full rows contain slide mapping, analytics, ranks, and user-facing
    draft state.  Returning an allowlist rather than popping known keys makes
    a future contextual field private by default.
    """
    out: list[dict] = []
    for row in (snippets or []):
        if not isinstance(row, dict):
            continue
        state = row.get("coach_state")
        state = state if isinstance(state, dict) else {}
        committed = has_committed_blind_label(state)
        out.append({
            "id": row.get("id"),
            "index": row.get("index"),
            "transcript": reveal_transcript_after_commit(
                row.get("transcript"), committed=committed),
            "audio_ref": row.get("audio_ref"),
            "start_offset_ms": row.get("start_offset_ms"),
            "duration_ms": row.get("duration_ms"),
            "coach_state": {
                "note": "",
                "tag": None,
                "surfaced": False,
                "rating_value": state.get("rating_value"),
                "rating_unrateable": bool(
                    state.get("rating_unrateable")
                ),
            },
        })
    return out
