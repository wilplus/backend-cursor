"""Typed read contracts for the student's Ideal Text notebook."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


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
