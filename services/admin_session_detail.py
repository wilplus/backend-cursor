"""The admin's comprehensive payload for one session (GET
/v2/admin/sessions/<session_id>).

Moved out of ``routes.v2.admin`` unchanged (founder 2026-10-12). The route
keeps the admin gate and the 500 boundary; the two audio-URL resolvers are
the route's and are handed in. Denormalised on purpose: the admin page
renders the conversation and the highlight reel without a round trip per
turn or per snippet.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from services.snippet_values import resolve_all


def _str_or_none(value: Any) -> Optional[str]:
    return str(value) if value else None


def snippet_start_time(snippet: dict) -> Optional[float]:
    """API-boundary seconds-float start time. Not a persisted column — every
    attempt to write it raises PGRST204 (services/db.py::
    update_snippet_boundaries); the canonical pair is start_offset_ms /
    duration_ms, so the old contract is synthesised at response time."""
    ms = snippet.get("start_offset_ms")
    return None if ms is None else round(float(ms) / 1000.0, 3)


def snippet_end_time(snippet: dict) -> Optional[float]:
    """API-boundary seconds-float end time (see ``snippet_start_time``)."""
    start_ms = snippet.get("start_offset_ms")
    dur_ms = snippet.get("duration_ms")
    if start_ms is None or dur_ms is None:
        return None
    return round((float(start_ms) + float(dur_ms)) / 1000.0, 3)


def _user_turn(s: dict, turn_audio_url: Callable) -> dict:
    return {
        "role": "user",
        "content": (s.get("transcript") or "").strip(),
        # Per-turn ORIGINAL audio URL — plays standalone in the chat bubble.
        "audio_url": turn_audio_url(s),
        "duration_ms": s.get("duration_ms"),
        # ZERO when audio_url points at the per-turn original file; the row's
        # own offset when it falls through to the concatenated full.webm.
        "start_offset_ms": (
            0 if (s.get("audio_segment_path") or "").strip()
            else int(s.get("start_offset_ms") or 0)
        ),
        "snippet_id": _str_or_none(s.get("id")),
        "turn_number": s.get("turn_number"),
        # PM-9: the six measures, resolved (the denormalized columns are dead).
        "metrics": resolve_all(s),
    }


def _turns(snippets: list, turn_audio_url: Callable) -> list:
    """Interview rows (turn_number set) as AI/user message pairs, ordered by
    turn then offset so within-turn order is stable."""
    rows = sorted((s for s in snippets if s.get("turn_number") is not None),
                  key=lambda s: (s.get("turn_number") or 0,
                                 s.get("start_offset_ms") or 0))
    turns: list[dict] = []
    for s in rows:
        question = (s.get("question_text") or "").strip()
        if question:
            turns.append({"role": "ai", "content": question,
                          "tone": s.get("question_tone"),
                          "turn_number": s.get("turn_number")})
        turns.append(_user_turn(s, turn_audio_url))
    return turns


def _highlight(s: dict, session_id: str, snippet_audio_url: Callable) -> dict:
    return {
        "id": _str_or_none(s.get("id")),
        "session_id": str(s.get("session_id")) if s.get("session_id") else str(session_id),
        "user_id": _str_or_none(s.get("user_id")),
        "recording_id": _str_or_none(s.get("recording_id")),
        "type": s.get("snippet_type") or s.get("coach_label"),
        "snippet_type": s.get("snippet_type"),
        # Provenance tag: "auto_extracted", "student", or NULL (legacy).
        "source_type": s.get("source_type"),
        "coach_label": s.get("coach_label"),
        "audio_url": snippet_audio_url(s),
        "audio_segment_path": s.get("audio_segment_path"),
        "storage_path": s.get("storage_path"),
        "transcript": s.get("transcript"),
        "duration_ms": s.get("duration_ms"),
        "start_offset_ms": s.get("start_offset_ms"),
        "admin_comment": s.get("admin_comment"),
        "is_skipped": bool(s.get("is_skipped", False)),
        "turn_number": s.get("turn_number"),
        "start_time": snippet_start_time(s),
        "end_time": snippet_end_time(s),
        # The coaching-outcome blob, NULL until the user answered turn 1 of
        # the contextual chat this snippet seeded.
        "follow_up_outcome": s.get("follow_up_outcome"),
        "created_at": s.get("created_at"),
    }


def _global_metrics(session: dict) -> dict:
    return {
        "wpm": session.get("global_wpm"),
        "fillers": session.get("global_fillers"),
        "pause_ms": session.get("global_pause_ms"),
        "dynamic_db": session.get("global_dynamic_db"),
        "pitch_center": session.get("global_pitch_center"),
        "energy": session.get("global_energy"),
        "kpi_score": session.get("kpi_score"),
        # Phase 11 — stickiness-topic; NULL until "Compute Metrics".
        "stickiness_top_topic": session.get("stickiness_top_topic"),
        "stickiness_score": session.get("stickiness_score"),
        "stickiness_topic_distribution": session.get(
            "stickiness_topic_distribution"),
        "stickiness_computed_at": session.get("stickiness_computed_at"),
        # Phase 17.1 — drift-guard verdict.
        "needs_admin_review": bool(session.get("needs_admin_review")),
        "drift_diagnostic": session.get("drift_diagnostic"),
        # Phase 18.x — the DB column is the legacy ai_task_alignment_comment.
        "session_kpi_narrative": session.get("ai_task_alignment_comment"),
        "session_kpi_narrative_ai_draft": session.get(
            "session_kpi_narrative_ai_draft"),
    }


def session_detail(database, session_id: str, *, turn_audio_url: Callable,
                   snippet_audio_url: Callable) -> Optional[dict]:
    """The payload, or None for an unknown session. One read for every
    snippet: interview turns AND extracted moments share the table,
    distinguished by whether `turn_number` is set."""
    session = database.takes.get_session_with_global_metrics(session_id)
    if not session:
        return None
    user_id = session.get("user_id")
    snippets = database.get_snippets_by_session(session_id) or []
    turns = _turns(snippets, turn_audio_url)
    # The highlight reel: extracted snippets only (turn_number IS NULL).
    highlights = [_highlight(s, session_id, snippet_audio_url)
                  for s in snippets if s.get("turn_number") is None]
    return {
        "id": str(session_id),
        "user_id": _str_or_none(user_id),
        "status": session.get("status"),
        "results_published_at": session.get("results_published_at"),
        "created_at": session.get("created_at"),
        "global_metrics": _global_metrics(session),
        "turns": turns,
        "snippets": highlights,
        "total_turns": len(turns),
        "total_snippets": len(highlights),
    }
