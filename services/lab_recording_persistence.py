"""Storage and database persistence for an accepted Lab recording."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

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
    upload_key: str,
    owner_principal_id: str,
    user_id: str | None,
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
    # Every accepted upload gets a fresh immutable Take id. Retry collapse is
    # handled before storage by the project-scoped idempotency contract; a
    # browser-provided session id can therefore never redirect this write.
    session_id = str(uuid.uuid4())
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

    try:
        database.v2_create_recording_session(
            session_id,
            owner_principal_id=owner_principal_id,
            user_id=user_id,
        )
    except Exception as exc:
        log.error(
            "lab: take row create failed: %s",
            exc,
            exc_info=True,
        )
        raise RecordingPersistenceError("Failed to create session") from exc
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
    """Persist context, origin, duration, and owner."""
    session_context.update(flow_tags)
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
        database.v2_set_session_recording(session_id, recording_id)
    except Exception as exc:
        log.warning("lab: link recording failed (non-fatal): %s", exc)
    return RecordingRow(duration, user_id)
