"""Typed read contracts for the student's Ideal Text notebook."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


class IdealTextHistoryStore(Protocol):
    """The one persistence capability historical Ideal Text reads require."""

    def get_ideal_text_version(
        self,
        arc_id: str,
        version: int,
    ) -> Mapping[str, Any] | None: ...


class IdealTextEditStore(Protocol):
    """The owner-scoped edit capability required by the live read."""

    def get_user_ideal_edit(
        self,
        arc_id: str,
        user_id: str,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True)
class IdealTextSource:
    """Canonical machine/version fields derived from the coach-owned row."""

    row: Mapping[str, Any]
    machine_text: str
    version: int | None


@dataclass(frozen=True)
class HistoricalRead:
    """A complete early response for a requested historical version."""

    payload: dict[str, Any]
    status: int


@dataclass(frozen=True)
class LiveTextRead:
    """The exact live text selected before suggestions and parts compose."""

    verified: bool
    text: str
    user_edited: bool
    prior_edit: dict[str, Any] | None


@dataclass(frozen=True)
class SuggestionDisplayRead:
    """Suggestion feature state and the resulting serve-time text copy."""

    enabled: bool
    text: str


@dataclass(frozen=True)
class IdealTextProjectRead:
    """Project/take/deck metadata derived from the ownership session read."""

    spoken_rows: list[Mapping[str, Any]]
    title: str | None
    latest_take_session_id: str | None
    can_record_take: bool
    presentation_ref: Any
    slide_titles: list[str]


def resolve_ideal_text_source(
    row: Mapping[str, Any] | None,
) -> IdealTextSource:
    """Resolve the machine copy without leaking unverified coach work."""
    source = row or {}
    coach_owned = bool(source.get("updated_by") or source.get("approved_at"))
    auto_text = (source.get("auto_text") or "").strip()
    fallback_text = (source.get("text") or "").strip()
    machine_text = auto_text or (fallback_text if not coach_owned else "")
    raw_version = source.get("version")
    version = raw_version if raw_version else (1 if machine_text else None)
    return IdealTextSource(source, machine_text, version)


def resolve_historical_read(
    arc_id: str,
    raw_version: Any,
    current_version: int | None,
    *,
    database: IdealTextHistoryStore,
) -> HistoricalRead | None:
    """Return an early historical response, or ``None`` for the live view."""
    if raw_version in (None, ""):
        return None
    try:
        requested_version = int(raw_version)
    except (TypeError, ValueError):
        return HistoricalRead({
            "code": "INVALID_INPUT",
            "error": "version must be an integer",
        }, 400)

    if current_version is not None and requested_version == current_version:
        return None

    snapshot = database.get_ideal_text_version(arc_id, requested_version)
    snapshot_text = (snapshot or {}).get("text") or ""
    if not snapshot or not snapshot_text.strip():
        return HistoricalRead({
            "arc_id": arc_id,
            "historical_unavailable": True,
            "requested_version": requested_version,
            "current_version": current_version,
        }, 200)

    from services.ideal_text_block import (
        extract_key_moments,
        sanitize_markers,
        strip_moment_markers,
    )

    moments = extract_key_moments(snapshot_text)
    key_moments = [{
        "id": moment.get("snippet_id"),
        "snippet_id": moment.get("snippet_id"),
        "anchor": moment.get("anchor") or "",
        "take_session_id": moment.get("take_session_id"),
    } for moment in moments]
    return HistoricalRead({
        "arc_id": arc_id,
        "version": requested_version,
        "historical": True,
        "status": "superseded",
        "current_version": current_version,
        "created_at": snapshot.get("created_at"),
        "text": sanitize_markers(strip_moment_markers(snapshot_text)),
        "key_moments": key_moments,
    }, 200)


def resolve_live_text(
    arc_id: str,
    user_id: str,
    source: IdealTextSource,
    *,
    database: IdealTextEditStore,
) -> LiveTextRead:
    """Select coach, machine, or owner-edited copy using legacy rules."""
    verified_version = source.row.get("verified_version")
    verified_text = (source.row.get("verified_text") or "").strip()
    verified = bool(
        source.version is not None
        and verified_version == source.version
        and verified_text
    )
    base_text = verified_text if verified else source.machine_text
    edit = database.get_user_ideal_edit(arc_id, user_id)
    user_edited = bool(
        edit
        and source.version is not None
        and edit.get("version") == source.version
        and (edit.get("text") or "").strip()
    )
    if user_edited:
        assert edit is not None
        text = edit["text"]
    else:
        text = base_text

    prior_edit = None
    try:
        if not user_edited and edit and source.version is not None:
            prior_text = (edit.get("text") or "").strip()
            prior_version = edit.get("version")
            if (
                prior_text
                and isinstance(prior_version, int)
                and not isinstance(prior_version, bool)
                and prior_version != source.version
            ):
                prior_edit = {"text": prior_text, "version": prior_version}
    except Exception:
        prior_edit = None

    return LiveTextRead(verified, text, user_edited, prior_edit)


def resolve_suggestion_display(
    arc_id: str,
    text: str,
    user_edited: bool,
    *,
    database: Any,
    suggestions_enabled: Callable[[], bool],
    applied_lookup: Callable[[list[Any]], Mapping[str, bool]],
    fold_applied: Callable[[str, list[dict[str, Any]]], str],
) -> SuggestionDisplayRead:
    """Fold accepted suggestions into the response without mutating storage."""
    enabled = suggestions_enabled()
    suggestions = (
        database.get_moment_suggestions_by_arc(arc_id) if enabled else {}
    )
    if not enabled or not suggestions:
        return SuggestionDisplayRead(enabled, text)

    from services.ideal_text_block import extract_key_moments

    moments = extract_key_moments(text)
    applied = applied_lookup([
        moment.get("take_session_id") for moment in moments
    ])
    if user_edited or not applied:
        return SuggestionDisplayRead(enabled, text)

    from services.ideal_decision_ledger import (
        frozen_approved_replacement,
        load_ledger,
    )

    decision_rows = load_ledger(database, arc_id)
    fold_info = []
    for moment in moments:
        moment_id = str(moment.get("snippet_id"))
        if moment_id not in suggestions or not applied.get(moment_id):
            continue
        suggestion = suggestions[moment_id]
        fold_info.append({
            "id": moment.get("snippet_id"),
            "take_session_id": moment.get("take_session_id"),
            "applied": True,
            "suggestion": {
                "kind": suggestion.get("kind"),
                "replacement": frozen_approved_replacement(
                    decision_rows, moment_id, suggestion
                ),
            },
        })
    return SuggestionDisplayRead(enabled, fold_applied(text, fold_info))


def resolve_project_read(
    sessions: Any,
    *,
    completed_spoken: Callable[[Any], list[Mapping[str, Any]]],
) -> IdealTextProjectRead:
    """Resolve take count, title, and deck identity with existing precedence."""
    spoken_rows = completed_spoken(sessions)
    spoken_rows.sort(key=lambda session: (session.get("take_index") or 0))

    title = None
    for session in spoken_rows:
        raw_context = session.get("intake_context")
        context = raw_context if isinstance(raw_context, dict) else {}
        topic = context.get("topic")
        if isinstance(topic, str) and topic.strip():
            title = topic.strip()

    latest_take_session_id = (
        str(spoken_rows[-1].get("id")) if spoken_rows else None
    )
    presentation_ref = None
    slide_titles: list[str] = []
    for session in spoken_rows:
        raw_context = session.get("intake_context")
        context = raw_context if isinstance(raw_context, dict) else {}
        slides = context.get("slides")
        if isinstance(slides, list) and len(slides) >= len(slide_titles):
            slide_titles = [
                ((slide.get("title") or "").strip()
                 if isinstance(slide, dict) else "")
                for slide in slides
            ]
        if presentation_ref is None and context.get("presentation_ref"):
            presentation_ref = context.get("presentation_ref")

    return IdealTextProjectRead(
        spoken_rows=spoken_rows,
        title=title,
        latest_take_session_id=latest_take_session_id,
        can_record_take=bool(spoken_rows),
        presentation_ref=presentation_ref,
        slide_titles=slide_titles,
    )
