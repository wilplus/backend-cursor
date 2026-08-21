"""Pure multipart-field parsing for the Lab recording upload route."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class RecordingLane:
    """The normalized recording lane carried into persistence and analysis."""

    recording_kind: str
    paired_session_id: str | None


@dataclass(frozen=True)
class RecordingIntakeError(Exception):
    """A stable API error produced before storage or processing begins."""

    code: str
    message: str
    status: int


def parse_recording_lane(
    form: Mapping[str, Any],
    *,
    is_valid_uuid: Callable[[str], bool],
) -> RecordingLane:
    """Validate read lanes and normalize all other kinds to spoken."""
    raw_kind = str(form.get("recording_kind") or "spoken").strip().lower()
    raw_pair = str(form.get("paired_session_id") or "").strip()
    if raw_kind == "read" and (not raw_pair or not is_valid_uuid(raw_pair)):
        raise RecordingIntakeError(
            "INVALID_INPUT",
            "A re-read needs the spoken take it belongs to "
            "(paired_session_id).",
            422,
        )

    raw_snippet = str(form.get("paired_snippet_id") or "").strip()
    if raw_kind == "read" and (
        not raw_snippet or not is_valid_uuid(raw_snippet)
    ):
        raise RecordingIntakeError(
            "INVALID_INPUT",
            "Reading your ideal text out loud has been retired. "
            "Record the next take instead.",
            422,
        )

    recording_kind = raw_kind if raw_kind in ("spoken", "read") else "spoken"
    paired_session_id = (
        raw_pair if raw_pair and is_valid_uuid(raw_pair) else None
    )
    return RecordingLane(recording_kind, paired_session_id)


def _optional_json(form: Mapping[str, Any], name: str) -> Any:
    raw = form.get(name)
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _optional_target_length(form: Mapping[str, Any]) -> int | None:
    raw = form.get("target_length_seconds")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _optional_clock_offset(form: Mapping[str, Any]) -> int | None:
    raw = form.get("slide_clock_offset_ms")
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def parse_session_context(
    form: Mapping[str, Any],
    *,
    parse_vocabulary: Callable[[Any], list | None],
) -> dict:
    """Build and validate the canonical session context from flat fields."""
    from services.intake_context import validate_intake_context_body

    return validate_intake_context_body(
        {
            "topic": form.get("topic"),
            "audience": form.get("audience"),
            "strategic_context": form.get("strategic_context"),
            "target_length_seconds": _optional_target_length(form),
            "domain_vocabulary": parse_vocabulary(
                form.get("domain_vocabulary")
            ),
            "slides": _optional_json(form, "slides"),
            "presentation_ref": form.get("presentation_ref") or None,
            "slide_advances": _optional_json(form, "slide_advances"),
            "slide_clock_offset_ms": _optional_clock_offset(form),
        },
        require_topic=True,
    )
