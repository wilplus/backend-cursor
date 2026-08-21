"""Project identity and retry guards for Lab recording intake."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from services.lab_recording_intake import RecordingIntakeError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectSelection:
    """Validated explicit project identity, if the client supplied one."""

    intent: str | None
    explicit_arc_id: str | None
    explicit_arc_sessions: tuple[dict, ...]


def validate_project_selection(
    form: Mapping[str, Any],
    *,
    user_id: Any,
    database: Any,
    is_valid_uuid: Callable[[str], bool],
    log: logging.Logger = logger,
) -> ProjectSelection:
    """Validate the explicit new/continue contract before any storage."""
    from services.explore_arc import validate_project_intent

    explicit_arc_id = str(form.get("continue_arc_id") or "").strip()
    intent, intent_error = validate_project_intent(
        form.get("project_intent"),
        form.get("arc_id"),
        explicit_arc_id,
    )
    if intent_error:
        log.warning(
            "lab: invalid project identity contract: %s",
            intent_error,
        )
        raise RecordingIntakeError(
            "INVALID_INPUT",
            "Something went wrong on our end.",
            400,
        )
    if not explicit_arc_id:
        return ProjectSelection(intent, None, ())
    if not is_valid_uuid(explicit_arc_id):
        raise RecordingIntakeError(
            "INVALID_INPUT",
            "continue_arc_id must be a UUID",
            400,
        )

    sessions: list = []
    owned = False
    if user_id:
        try:
            sessions = database.get_arc_sessions(explicit_arc_id) or []
            owned = any(
                str(session.get("user_id")) == str(user_id)
                for session in sessions
            )
        except Exception as error:
            log.warning(
                "lab: continue_arc ownership check failed arc=%s: %s",
                explicit_arc_id,
                error,
            )
    if not owned:
        raise RecordingIntakeError(
            "NOT_FOUND",
            "project not found",
            404,
        )
    return ProjectSelection(intent, explicit_arc_id, tuple(sessions))


def ensure_presentation_unchanged(
    selection: ProjectSelection,
    session_context: dict,
) -> None:
    """Keep a continued project's established slide structure immutable."""
    if not selection.explicit_arc_sessions:
        return
    from services.presentation_change_intent import deck_matches_recorded_project

    if deck_matches_recorded_project(
        list(selection.explicit_arc_sessions),
        session_context,
    ):
        return
    raise RecordingIntakeError(
        "PRESENTATION_LOCKED",
        "Your current roadmap is connected to these slides. "
        "Create a new project for the updated deck.",
        409,
    )


def find_duplicate_upload(
    form: Mapping[str, Any],
    *,
    database: Any,
    context_document: dict | None,
    log: logging.Logger = logger,
) -> tuple[str, dict | None]:
    """Find a captured-take retry and heal its optional context-document gap."""
    upload_key = str(form.get("upload_idempotency_key") or "").strip()
    if not upload_key:
        return "", None
    duplicate = database.v2_find_session_by_upload_key(upload_key)
    if not duplicate:
        return upload_key, None

    duplicate_arc = duplicate.get("arc_id")
    if context_document and duplicate_arc:
        database.upsert_arc_context_document(
            duplicate_arc,
            context_document["text"],
            context_document["pages"],
            context_document["chars"],
            filename=context_document.get("filename"),
            truncated=context_document["truncated"],
        )
    log.info(
        "lab: duplicate upload collapsed key=%s -> %s",
        upload_key,
        duplicate.get("id"),
    )
    return upload_key, duplicate
