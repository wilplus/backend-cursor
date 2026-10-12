"""A student's drill-down for the coach (GET /v2/coach/students/<user_id>).

Moved out of ``routes.v2.coach`` unchanged (founder 2026-10-12). Pseudonymized
by construction: the route adds the pseudonym, and nothing here returns a
name or an email. `goal` is user free-text and may self-identify — inherent,
not scrubbable (Flag 1: pseudonymized-default).
"""
from __future__ import annotations

from typing import Optional


def _session_state(s: dict) -> str:
    if s.get("results_published_at"):
        return "insights_ready"
    if s.get("status") == "pending_admin_review":
        return "review_pending"
    return "readout_ready"


def _review_state(s: dict) -> str:
    """Founder 2026-07-15: "saved feedback means REVIEWED." Three explicit
    states beside the legacy `state` (additive — the FE maps review_state
    safe-ahead): delivered (published) → reviewed (coach saved the take's
    feedback) → to_review."""
    if s.get("results_published_at"):
        return "delivered"
    if s.get("coach_feedback_saved_at"):
        return "reviewed"
    return "to_review"


def _feeling_by_session(database, rows: list) -> dict:
    """U10 rollup — the feeling the student named per session, mapped by
    session_id (one batch read) so the coach sees the felt-state spread
    across the student's takes in one place. Coach-only (split-sink)."""
    out: dict = {}
    for fr in database.get_feelings_by_sessions([s.get("id") for s in rows]):
        out.setdefault(fr.get("session_id"), fr.get("feeling"))
    return out


def _session_row(s: dict, feelings: dict, reread_parents: set) -> dict:
    ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
    return {
        "session_id": s.get("id"),
        "take_index": s.get("take_index"),
        "topic": (ctx or {}).get("topic") or "",
        "created_at": s.get("created_at"),
        "state": _session_state(s),
        "review_state": _review_state(s),
        "arc_id": s.get("arc_id"),
        "feeling": feelings.get(s.get("id")),
        "has_reread": str(s.get("id")) in reread_parents,
    }


def _ideal_ready_arcs(database, sessions: list) -> list:
    """"Ideal text ready to review" badges (founder 2026-07-15) — the arcs
    with a persisted MACHINE draft awaiting the coach (unapproved). ONE READ
    FOR EVERY PROJECT, not one each."""
    rows = database.ideal_text.get_coach_arc_ideal_texts(
        [s.get("arc_id") for s in sessions if s.get("arc_id")]) or {}
    return [str(aid) for aid, row in rows.items()
            if row and (row.get("text") or "").strip()
            and not row.get("approved_at")]


def student_detail(database, user_id: str) -> Optional[dict]:
    """{domain, goal, ideal_ready_arc_ids, previous_goal, goal_changed_at,
    sessions}, or None when the id has no footprint at all.

    A real roster student always has >=1 Lab session; None only when there
    are no sessions AND no profile, so a transient sessions-read hiccup
    can't false-404 a known student."""
    prof = database.get_user_profile(user_id) or {}
    rows = database.takes.v2_list_user_lab_sessions(user_id) or []
    if not rows and not (prof.get("domain") or prof.get("goal")):
        return None
    feelings = _feeling_by_session(database, rows)
    # Founder 2026-07-16: a mid-take RE-READ is part of its parent take —
    # never an extra row on the drill-down. Hide read rows; mark parents.
    reread_parents = {
        str(s.get("paired_session_id")) for s in rows
        if s.get("paired_session_id")
    }
    sessions = [_session_row(s, feelings, reread_parents) for s in rows
                if not (s.get("recording_kind") == "read"
                        or s.get("paired_session_id"))]
    return {
        "domain": prof.get("domain") or "",
        "goal": prof.get("goal") or "",
        "ideal_ready_arc_ids": _ideal_ready_arcs(database, sessions),
        # Goal-change context: what the goal WAS before the last change
        # and when. Empty when the goal has never been changed.
        "previous_goal": prof.get("previous_goal") or "",
        "goal_changed_at": prof.get("goal_changed_at") or "",
        "sessions": sessions,
    }
