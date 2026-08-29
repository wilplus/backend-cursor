"""Storage and database persistence for an accepted Lab recording."""
from __future__ import annotations

import os
import uuid
import hashlib
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
    storage_provider: str
    content_type: str
    exact_bytes_sha256: str
    verification_method: str


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
    acquisition_principal_id: str | None = None,
    user_id: str | None,
    database: Any,
    deadline: Any,
    log: Any,
) -> StoredRecording:
    """Store parent audio and ensure its owning session exists."""
    from services.lab_audio_storage import (
        get_exact_storage_object_bytes,
        lab_audio_public_url,
        put_lab_audio_bytes,
        storage_provider as lab_storage_provider,
    )
    from services.processing_authorization import ProcessingAuthorizationService

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
    exact_sha256 = hashlib.sha256(audio_bytes).hexdigest()
    storage_provider = lab_storage_provider()
    authorization = ProcessingAuthorizationService(database)
    verification_method = "trusted_object_checksum_sha256"
    if authorization.enforced:
        try:
            stored_bytes = get_exact_storage_object_bytes(
                storage_key,
                bucket=bucket,
                storage_provider=storage_provider,
            )
            if hashlib.sha256(stored_bytes).hexdigest() != exact_sha256:
                raise ValueError("stored audio checksum mismatch")
            verification_method = "read_after_write_sha256"
        except Exception as exc:
            try:
                authorization.queue_orphan(
                    acquisition_principal_id=(
                        acquisition_principal_id or owner_principal_id
                    ),
                    storage_provider=storage_provider,
                    bucket=bucket, object_key=storage_key,
                    exact_bytes_sha256=exact_sha256,
                    reason_code="UPLOAD_VERIFICATION_FAILED",
                )
            except Exception:
                pass
            raise RecordingPersistenceError(
                "Stored recording verification failed"
            ) from exc
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
        try:
            authorization.queue_orphan(
                acquisition_principal_id=(
                    acquisition_principal_id or owner_principal_id
                ),
                storage_provider=storage_provider,
                bucket=bucket, object_key=storage_key,
                exact_bytes_sha256=exact_sha256,
                reason_code="SESSION_CREATE_FAILED",
            )
        except Exception:
            pass
        raise RecordingPersistenceError("Failed to create session") from exc
    database.v2_set_session_upload_key(session_id, upload_key)

    return StoredRecording(
        session_id=session_id,
        recording_id=recording_id,
        bucket=bucket,
        storage_key=storage_key,
        audio_url=audio_url,
        storage_provider=storage_provider,
        content_type=content_type,
        exact_bytes_sha256=exact_sha256,
        verification_method=verification_method,
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
