"""Fail-closed media transport for the MLC-3 first-client pilot.

The database reservation is always durable before object storage is touched.
If the provider stores bytes but its acknowledgement is lost, the unresolved
recovery row remains discoverable by deletion/reconciliation.  Finalization is
only attempted after a read-after-write SHA-256 check.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol


class PilotStorage(Protocol):
    def put(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        ...

    def get(self, *, bucket: str, key: str) -> bytes:
        ...


class CoachVideoR2Storage:
    """Existing coach-video bucket behind the common verified interface."""

    def put(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        from services.coach_video_storage import put_coach_object_r2_bytes

        put_coach_object_r2_bytes(bucket, key, body, content_type)

    def get(self, *, bucket: str, key: str) -> bytes:
        from services.coach_video_storage import get_coach_object_r2_bytes

        return get_coach_object_r2_bytes(bucket, key)


class PracticeAudioR2Storage:
    """Existing private user-media bucket behind the verified interface."""

    def put(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        from services.user_media_storage import put_user_media_r2_bytes

        written_bucket = put_user_media_r2_bytes(key, body, content_type)
        if written_bucket != bucket:
            raise RuntimeError("PILOT_MEDIA_BUCKET_MISMATCH")

    def get(self, *, bucket: str, key: str) -> bytes:
        from services.user_media_storage import get_user_media_r2_bytes

        return get_user_media_r2_bytes(key, bucket=bucket)


@dataclass(frozen=True)
class ReservedObject:
    recovery_id: str
    bucket: str
    object_key: str
    exact_bytes_sha256: str
    byte_size: int
    content_type: str
    write_required: bool = True
    attempt_index: int | None = None


@dataclass(frozen=True)
class FinalizedObject:
    recovery_id: str
    media_object_id: str
    bucket: str
    object_key: str
    exact_bytes_sha256: str
    byte_size: int
    content_type: str


Reserve = Callable[..., ReservedObject]
Finalize = Callable[..., str]
RecordWriteStarted = Callable[[ReservedObject], None]
RecordWriteAcknowledged = Callable[[ReservedObject], None]


def store_exact_object(
    *,
    body: bytes,
    content_type: str,
    reserve: Reserve,
    finalize: Finalize,
    storage: PilotStorage,
    record_write_started: RecordWriteStarted,
    record_write_acknowledged: RecordWriteAcknowledged,
) -> FinalizedObject:
    """Reserve, store, verify and finalize one immutable object.

    Callers supply operation-specific database functions.  This adapter never
    marks an ambiguous provider failure as abandoned or deleted; the durable
    recovery remains unresolved until a reconciler proves the leaf state.
    """
    if not body:
        raise ValueError("PILOT_MEDIA_EMPTY")
    digest = sha256(body).hexdigest()
    reserved = reserve(
        exact_bytes_sha256=digest,
        byte_size=len(body),
        content_type=content_type,
    )
    if (
        reserved.exact_bytes_sha256 != digest
        or reserved.byte_size != len(body)
        or reserved.content_type != content_type
    ):
        raise RuntimeError("PILOT_MEDIA_RESERVATION_CONFLICT")

    if reserved.write_required:
        record_write_started(reserved)
        storage.put(
            bucket=reserved.bucket,
            key=reserved.object_key,
            body=body,
            content_type=content_type,
        )
    persisted = storage.get(bucket=reserved.bucket, key=reserved.object_key)
    if sha256(persisted).hexdigest() != digest or len(persisted) != len(body):
        raise RuntimeError("PILOT_MEDIA_READ_AFTER_WRITE_MISMATCH")
    record_write_acknowledged(reserved)
    media_object_id = finalize(
        recovery=reserved,
        verification_method="read_after_write_sha256",
    )
    if not media_object_id:
        raise RuntimeError("PILOT_MEDIA_FINALIZATION_FAILED")
    return FinalizedObject(
        recovery_id=reserved.recovery_id,
        media_object_id=str(media_object_id),
        bucket=reserved.bucket,
        object_key=reserved.object_key,
        exact_bytes_sha256=digest,
        byte_size=len(body),
        content_type=content_type,
    )
