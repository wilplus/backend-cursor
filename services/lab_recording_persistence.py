"""Storage and database persistence for an accepted Lab recording."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from services.lab_session_identity import choose_guest_session_id


@dataclass(frozen=True)
class RecordingPersistenceError(Exception):
    """A stable user-facing failure at a required persistence boundary."""

    message: str


@dataclass(frozen=True)
class StoredRecording:
    """Parent audio coordinates created before arc assignment."""

    session_id: str
    recording_id: str
    bucket: str
    storage_key: str
    audio_url: str


@dataclass(frozen=True)
class RecordingRow:
    """Values from the durable recording row needed by analysis."""

    duration_seconds: int
    uploader_id: str | None


def store_recording_audio(
    audio_file: Any,
    audio_bytes: bytes,
    *,
    requested_session_id: str | None,
    upload_key: str | None,
    database: Any,
    deadline: Any,
    log: Any,
) -> StoredRecording:
    """Store parent audio and ensure its owning session exists."""
    from services.lab_audio_storage import (
        lab_audio_public_url,
        put_lab_audio_bytes,
    )

    deadline.check("store")
    session_id = choose_guest_session_id(
        requested_session_id,
        database=database,
        log=log,
    )
    recording_id = str(uuid.uuid4())
    extension = os.path.splitext(
        getattr(audio_file, "filename", None) or ""
    )[1] or ".webm"
    storage_key = (
        f"willab_lab/{session_id}/recording_{uuid.uuid4().hex}{extension}"
    )
    content_type = (
        getattr(audio_file, "mimetype", None) or "audio/webm"
    ).strip() or "audio/webm"

    try:
        bucket = put_lab_audio_bytes(storage_key, audio_bytes, content_type)
    except Exception as exc:
        log.error("lab: parent upload failed: %s", exc, exc_info=True)
        raise RecordingPersistenceError("Failed to store recording") from exc
    audio_url = (
        lab_audio_public_url(storage_key)
        or f"s3://{bucket}/{storage_key}"
    )

    if not database.v2_get_session_by_id(session_id):
        try:
            database.v2_create_guest_session(session_id)
        except Exception as exc:
            log.error(
                "lab: guest session create failed: %s",
                exc,
                exc_info=True,
            )
            raise RecordingPersistenceError("Failed to create session") from exc
    if upload_key:
        database.v2_set_session_upload_key(session_id, upload_key)

    return StoredRecording(
        session_id=session_id,
        recording_id=recording_id,
        bucket=bucket,
        storage_key=storage_key,
        audio_url=audio_url,
    )


def persist_session_metadata(
    session_id: str,
    session_context: dict[str, Any],
    *,
    flow_tags: Mapping[str, Any],
    duration_seconds: float | int | None,
    user_id: str | None,
    database: Any,
) -> None:
    """Persist context, origin, duration, owner, and private drift signal."""
    session_context.update(flow_tags)
    if session_context.get("named_emotion"):
        try:
            from services.named_emotion import log_drift_signal

            log_drift_signal(
                user_id,
                session_id,
                session_context["named_emotion"],
            )
        except Exception:
            pass

    database.set_session_intake_context(session_id, session_context)
    database.set_session_source(session_id, "audit_upload")
    database.set_session_presentation_duration(session_id, duration_seconds)
    if user_id:
        database.set_session_user_id(session_id, user_id)


def persist_recording_row(
    *,
    form: Mapping[str, Any],
    session_id: str,
    recording_id: str,
    storage_key: str,
    audio_url: str,
    gate: Mapping[str, Any],
    user_id: str | None,
    arc_id: str | None,
    take_index: int | None,
    database: Any,
    log: Any,
) -> RecordingRow:
    """Persist private signals and the recording row with schema fallback."""
    from services.feelings import normalize_feeling
    from services.priming import (
        normalize_priming_condition,
        normalize_priming_phrase,
    )

    feeling = normalize_feeling(form.get("feeling"))
    if feeling:
        database.insert_recording_feeling(
            session_id=session_id,
            feeling=feeling,
            user_id=user_id,
            recording_id=recording_id,
            arc_id=arc_id,
            take_index=take_index,
        )

    priming_condition = normalize_priming_condition(
        form.get("priming_condition")
    )
    priming_phrase = normalize_priming_phrase(form.get("priming_phrase"))
    if priming_condition or priming_phrase:
        database.set_session_priming(
            session_id,
            priming_condition,
            priming_phrase,
        )

    try:
        duration = int(round(float(gate.get("duration_sec") or 0)))
    except (TypeError, ValueError):
        duration = 0
    payload = {
        "id": recording_id,
        "user_id": user_id,
        "session_v2_id": session_id,
        "storage_path": storage_key,
        "audio_url": audio_url,
        "duration": duration,
        "recording_origin": "willab_lab",
    }
    try:
        database.create_recording(payload)
    except Exception as exc:
        error = str(exc).lower()
        if "recording_origin" in error or "pgrst204" in error:
            database.create_recording({
                key: value
                for key, value in payload.items()
                if key != "recording_origin"
            })
        else:
            log.error(
                "lab: create_recording failed: %s",
                exc,
                exc_info=True,
            )
            raise RecordingPersistenceError(
                "Failed to create recording"
            ) from exc
    try:
        database.v2_set_guest_session_recording(session_id, recording_id)
    except Exception as exc:
        log.warning("lab: link recording failed (non-fatal): %s", exc)
    return RecordingRow(duration, user_id)
