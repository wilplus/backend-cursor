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


def reveal_acoustic_features_after_commit(
    features: Any, *, committed: bool
) -> dict | None:
    """Release raw acoustic reference data only after the blind answer.

    Returning ``None`` rather than an empty feature object before commitment
    keeps the data out of the wire payload altogether. The caller remains
    responsible for supplying the canonical, display-only feature projection.
    """
    if not committed or not isinstance(features, dict):
        return None
    return dict(features)


def can_reveal_acoustic_features(rows: Any, *, requested: bool) -> bool:
    """Whether a second-pass queue may contain any acoustic measurements."""
    if not requested or not isinstance(rows, list):
        return False
    return all(
        isinstance(row, dict) and row.get("label") is not None
        for row in rows
    )


def redact_contextual_snippets(snippets: Any) -> list[dict]:
    """Allowlist the blind evidence packet while the pass is incomplete.

    The full rows contain analytics, ranks, and user-facing draft state.
    Returning an allowlist rather than popping known keys makes a future
    contextual field private by default.

    TWO FIELDS WERE ADDED TO THIS ALLOWLIST ON 2026-09-24, both by explicit
    founder ruling, and both are widenings of what a blind rater may see. They
    are listed here rather than only at their keys because adding to this list
    is the only way context reaches a blind screen, and a reader who does not
    know that will not know what they are looking at.

    ``slide`` — FOUNDER OVERRIDE OF THE BLIND-COACH FENCE. "I want as a coach
    to see the slide at the top; to know on which slide they are talking
    about." Until now the confidence label was collected from the voice alone,
    which is what this module's own first sentence describes and what the
    frontend's structural early return enforces. It no longer is. The founder
    was shown the fence, shown the compliant alternative (reveal the slide on
    the answer, as the transcript already does), and chose the override
    deliberately; only the founder can move that fence, so this is the one
    change that could not be made any other way.

    WHAT THE OVERRIDE COSTS, AND WHAT PAYS FOR IT. The instrument changed
    mid-collection: every label before today was voice-only and every label
    after it is voice-plus-slide, and once stored the two are
    indistinguishable — the same defect ``saw_model_output`` exists to prevent
    for the machine read. So the rating write now stamps ``saw_slide`` the same
    way, server-supplied and defaulting to blind. The corpus can then separate
    the two instruments instead of silently mixing them. Do not remove that
    stamp while this key is on the list.

    ``bookmarked`` — whether the user met this moment as a bookmark. A bare
    boolean and nothing else: no tier, no colour, no band, no ordering. The
    coach learns that the moment was surfaced, never what the machine thought
    of it, which is the line AC-9 draws. Founder ruling the same day, taken
    with the signal named out loud: the coach's answer is only comparable to
    the user's if both are about the same moments.
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
            # Founder override, 2026-09-24 — see this function's docstring.
            # Paired with the `saw_slide` stamp on the rating write.
            "slide": row.get("slide"),
            # A bare boolean: surfaced to the user, or not. Never the tier.
            "bookmarked": bool(row.get("bookmarked")),
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
