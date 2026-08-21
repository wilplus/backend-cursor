"""Project-arc assignment and take numbering for Lab recordings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from services.best_presentation import spoken_arc_sessions
from services.explore_arc import resolve_arc


@dataclass(frozen=True)
class ArcAssignment:
    """The immutable project coordinates carried into analysis."""

    arc_id: str | None
    take_index: int | None
    take_count: int | None


def _number_explicit_take(
    explicit_arc_id: str,
    fallback_index: int | None,
    database: Any,
) -> int:
    """Explicit continuation always trusts server-side spoken take history."""
    try:
        return len(spoken_arc_sessions(
            database.get_arc_sessions(explicit_arc_id) or []
        )) + 1
    except Exception:
        return max(1, fallback_index or 1)


def assign_recording_arc(
    form: Mapping[str, Any],
    *,
    session_context: Mapping[str, Any],
    recording_kind: str,
    paired_session_id: str | None,
    explicit_arc_id: str | None,
    project_intent: str | None,
    user_id: str | None,
    session_id: str,
    database: Any,
    continue_deck_arc: Callable[..., tuple[str, int]],
    continue_topic_arc: Callable[..., tuple[str, int]],
) -> ArcAssignment:
    """Resolve, continue, number, and persist one recording's project arc."""
    arc_id, take_index = resolve_arc(
        form.get("explore_session"),
        form.get("arc_id"),
        form.get("take_index"),
    )

    if explicit_arc_id:
        arc_id = explicit_arc_id
        take_index = _number_explicit_take(
            explicit_arc_id,
            take_index,
            database,
        )

    if recording_kind == "read" and paired_session_id:
        paired = database.v2_get_session_by_id(paired_session_id) or {}
        if paired.get("arc_id"):
            arc_id = paired.get("arc_id")
        if paired.get("take_index"):
            take_index = int(paired["take_index"])

    should_infer_continuation = bool(
        user_id
        and arc_id
        and recording_kind != "read"
        and not explicit_arc_id
        and project_intent != "new"
    )
    if should_infer_continuation:
        slides = session_context.get("slides") or []
        presentation_ref = session_context.get("presentation_ref")
        if slides and presentation_ref:
            arc_id, take_index = continue_deck_arc(
                user_id,
                slides,
                arc_id,
                take_index,
            )
        else:
            arc_id, take_index = continue_topic_arc(
                user_id,
                session_context.get("topic"),
                arc_id,
                take_index,
            )

    if recording_kind == "read":
        if arc_id:
            database.set_session_arc(session_id, arc_id, take_index)
        database.set_session_recording_kind(
            session_id,
            "read",
            paired_session_id,
        )
        return ArcAssignment(arc_id, take_index, take_index)

    if not arc_id:
        return ArcAssignment(arc_id, take_index, None)

    existing = database.v2_get_session_by_id(session_id) or {}
    if existing.get("arc_id") and existing.get("take_index"):
        arc_id = existing["arc_id"]
        take_index = int(existing["take_index"])
    else:
        count = database.count_arc_sessions(
            arc_id,
            exclude_session_id=session_id,
        )
        if count is not None:
            take_index = count + 1
        database.set_session_arc(session_id, arc_id, take_index)
    return ArcAssignment(arc_id, take_index, take_index)
