"""Private user-media transport for Confident Moment Bundle playback.

The browser never receives an object-store identity. PostgreSQL issues an exact
read authority before R2 and a distinct stateless emit authorization afterward.
Bytes stay buffered until that final authorization and a fresh digest agree.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import random
import re
import threading
import time
from typing import Any, Callable, Protocol
import uuid


MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_RESERVED_BYTES = 50 * 1024 * 1024
R2_INTERNAL_DEADLINE_SECONDS = 7.5
BUFFER_TTL_SECONDS = 2.0
DATABASE_PHASE_BUDGET_SECONDS = 0.5
LOCAL_EMIT_BUDGET_SECONDS = 0.5


class ConfidentMomentUserReadRetry(RuntimeError):
    code = "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED"


class ConfidentMomentSourceMediaPolicyInvalid(RuntimeError):
    code = "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID"


class PrivateObjectReader(Protocol):
    def read_exact(
        self, *, bucket: str, object_key: str, byte_size: int,
        expected_sha256: str, monotonic: Callable[[], float],
    ) -> bytes: ...


@dataclass(frozen=True)
class _Reservation:
    byte_size: int


class BufferedPlaybackAdmission:
    """Process-local admission for exact-size source buffers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._bytes = 0

    def reserve(self, byte_size: int) -> _Reservation:
        if byte_size <= 0 or byte_size > MAX_SOURCE_BYTES:
            raise ConfidentMomentSourceMediaPolicyInvalid(
                ConfidentMomentSourceMediaPolicyInvalid.code
            )
        with self._lock:
            if self._bytes + byte_size > MAX_RESERVED_BYTES:
                raise ConfidentMomentUserReadRetry(
                    ConfidentMomentUserReadRetry.code
                )
            self._count += 1
            self._bytes += byte_size
        return _Reservation(byte_size=byte_size)

    def release(self, reservation: _Reservation) -> None:
        with self._lock:
            if self._count < 1 or self._bytes < reservation.byte_size:
                raise RuntimeError("CONFIDENT_MOMENT_BUFFER_ACCOUNTING_INVALID")
            self._count -= 1
            self._bytes -= reservation.byte_size

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return self._count, self._bytes


SOURCE_PLAYBACK_ADMISSION = BufferedPlaybackAdmission()


_AUTHORITY_KEYS = {
    "contract_version", "authority_sha256", "acquisition_principal_id",
    "bundle_id", "bundle_attachment_id", "project_id", "source_take_id",
    "feedback_membership_id", "feedback_candidate_id", "evidence_span_id",
    "canonical_feedback_presentation_id", "recording_attempt_id",
    "audio_lineage_id", "media_object_id", "bucket", "object_key",
    "object_version", "byte_size", "exact_bytes_sha256", "content_type",
    "rollout_revision_id", "enrollment_revision_id", "policy_id",
    "authorization_receipt_id", "dataset_eligible",
}


def validate_source_playback_authority(
    value: Any, *, principal_id: str, bundle_id: str, attachment_id: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _AUTHORITY_KEYS:
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    if (
        value.get("contract_version")
        != "confident-moment-source-playback-authority-v1"
        or value.get("acquisition_principal_id") != principal_id
        or value.get("bundle_id") != bundle_id
        or value.get("bundle_attachment_id") != attachment_id
        or value.get("dataset_eligible") is not False
    ):
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    for field in ("authority_sha256", "exact_bytes_sha256"):
        if not isinstance(value.get(field), str) or not re.fullmatch(
            r"[0-9a-f]{64}", value[field]
        ):
            raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    for field in (
        "acquisition_principal_id", "bundle_id", "bundle_attachment_id",
        "project_id", "source_take_id", "feedback_membership_id",
        "feedback_candidate_id", "evidence_span_id",
        "canonical_feedback_presentation_id", "recording_attempt_id",
        "audio_lineage_id", "media_object_id", "rollout_revision_id",
        "enrollment_revision_id", "policy_id", "authorization_receipt_id",
    ):
        raw = value.get(field)
        try:
            if not isinstance(raw, str) or str(uuid.UUID(raw)) != raw:
                raise ValueError
        except (ValueError, AttributeError):
            raise RuntimeError(
                "CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID"
            ) from None
    byte_size = value.get("byte_size")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int):
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    if byte_size <= 0 or byte_size > MAX_SOURCE_BYTES:
        raise ConfidentMomentSourceMediaPolicyInvalid(
            ConfidentMomentSourceMediaPolicyInvalid.code
        )
    if not isinstance(value.get("content_type"), str) or not value[
        "content_type"
    ].startswith("audio/"):
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    if not isinstance(value.get("bucket"), str) or not value["bucket"].strip():
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    if not isinstance(value.get("object_key"), str) or not value[
        "object_key"
    ].strip():
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    if not isinstance(value.get("object_version"), str) or not value[
        "object_version"
    ].strip():
        raise RuntimeError("CONFIDENT_MOMENT_SOURCE_PLAYBACK_AUTHORITY_INVALID")
    return value


class R2ExactPrivateObjectReader:
    """One bounded Cloudflare R2 request with no retries or presigned URL."""

    def __init__(
        self, *, client_provider: Callable[[], Any] | None = None,
        bucket_provider: Callable[[], str] | None = None,
    ) -> None:
        self._client_provider = client_provider
        self._bucket_provider = bucket_provider

    def read_exact(
        self, *, bucket: str, object_key: str, byte_size: int,
        expected_sha256: str, monotonic: Callable[[], float] = time.monotonic,
    ) -> bytes:
        from services.user_media_storage import require_user_media_r2

        required_bucket = (
            self._bucket_provider or require_user_media_r2
        )()
        if bucket != required_bucket:
            raise RuntimeError("CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID")

        started = monotonic()

        def require_time() -> None:
            if monotonic() - started >= R2_INTERNAL_DEADLINE_SECONDS:
                raise ConfidentMomentUserReadRetry(
                    ConfidentMomentUserReadRetry.code
                )

        require_time()
        if self._client_provider is not None:
            client = self._client_provider()
        else:
            import boto3
            from botocore.config import Config as BotoConfig
            from config import Config

            client = boto3.client(
                "s3",
                endpoint_url=(
                    f"https://{str(Config.R2_ACCOUNT_ID).strip()}"
                    ".r2.cloudflarestorage.com"
                ),
                aws_access_key_id=str(Config.R2_ACCESS_KEY_ID).strip(),
                aws_secret_access_key=str(Config.R2_SECRET_ACCESS_KEY).strip(),
                config=BotoConfig(
                    signature_version="s3v4", connect_timeout=0.2,
                    read_timeout=0.2,
                    retries={"max_attempts": 0},
                ),
                region_name="auto",
            )
        stream = None
        try:
            require_time()
            response = client.get_object(Bucket=bucket, Key=object_key.lstrip("/"))
            content_length = response.get("ContentLength")
            if (
                isinstance(content_length, bool)
                or not isinstance(content_length, int)
                or content_length != byte_size
            ):
                raise ConfidentMomentSourceMediaPolicyInvalid(
                    ConfidentMomentSourceMediaPolicyInvalid.code
                )
            stream = response["Body"]
            chunks: list[bytes] = []
            remaining = byte_size
            digest = sha256()
            while remaining:
                require_time()
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    raise ConfidentMomentSourceMediaPolicyInvalid(
                        ConfidentMomentSourceMediaPolicyInvalid.code
                    )
                if len(chunk) > remaining:
                    raise ConfidentMomentSourceMediaPolicyInvalid(
                        ConfidentMomentSourceMediaPolicyInvalid.code
                    )
                chunks.append(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            require_time()
            if digest.hexdigest() != expected_sha256:
                raise ConfidentMomentSourceMediaPolicyInvalid(
                    ConfidentMomentSourceMediaPolicyInvalid.code
                )
            body = b"".join(chunks)
            require_time()
            return body
        finally:
            if stream is not None:
                stream.close()


ResolveAuthority = Callable[[], dict[str, Any]]
AuthorizeEmit = Callable[[str, str, str], dict[str, Any]]


_EMIT_AUTHORIZATION_KEYS = {
    "contract_version", "playback_request_id", "acquisition_principal_id",
    "bundle_id", "bundle_attachment_id", "authority_sha256",
    "buffered_bytes_sha256", "authorized_at", "emit_authorized",
    "dataset_eligible", "emit_authorization_sha256",
}


def validate_and_consume_emit_authorization(
    value: Any, *, playback_request_id: str, principal_id: str,
    bundle_id: str, attachment_id: str, authority_sha256: str,
    buffered_body: bytes, window_started_at: float,
    buffer_completed_at: float, monotonic: Callable[[], float],
    already_consumed: bool,
) -> bool:
    """Consume one request-local stateless authorization exactly once."""
    if already_consumed:
        raise ConfidentMomentSourceMediaPolicyInvalid(
            ConfidentMomentSourceMediaPolicyInvalid.code
        )
    buffered_sha256 = sha256(buffered_body).hexdigest()
    now = monotonic()
    if (
        now - window_started_at > LOCAL_EMIT_BUDGET_SECONDS
        or now - buffer_completed_at > BUFFER_TTL_SECONDS
    ):
        raise ConfidentMomentUserReadRetry(ConfidentMomentUserReadRetry.code)
    if type(value) is not dict or set(value) != _EMIT_AUTHORIZATION_KEYS:
        raise ConfidentMomentSourceMediaPolicyInvalid(
            ConfidentMomentSourceMediaPolicyInvalid.code
        )
    if (
        value.get("contract_version")
        != "confident-moment-source-playback-emit-v1"
        or value.get("playback_request_id") != playback_request_id
        or value.get("acquisition_principal_id") != principal_id
        or value.get("bundle_id") != bundle_id
        or value.get("bundle_attachment_id") != attachment_id
        or value.get("authority_sha256") != authority_sha256
        or value.get("buffered_bytes_sha256") != buffered_sha256
        or value.get("emit_authorized") is not True
        or value.get("dataset_eligible") is not False
        or not isinstance(value.get("authorized_at"), str)
        or not value["authorized_at"].strip()
        or not isinstance(value.get("emit_authorization_sha256"), str)
        or re.fullmatch(
            r"[0-9a-f]{64}", value["emit_authorization_sha256"]
        ) is None
    ):
        raise ConfidentMomentSourceMediaPolicyInvalid(
            ConfidentMomentSourceMediaPolicyInvalid.code
        )
    return True


def load_confident_moment_source_bytes(
    *,
    resolve_authority: ResolveAuthority,
    authorize_emit: AuthorizeEmit,
    principal_id: str,
    bundle_id: str,
    attachment_id: str,
    reader: PrivateObjectReader | None = None,
    admission: BufferedPlaybackAdmission = SOURCE_PLAYBACK_ADMISSION,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
) -> tuple[bytes, str]:
    """Execute D46's three phases and release bytes only after phase 3."""
    before = validate_source_playback_authority(
        resolve_authority(), principal_id=principal_id, bundle_id=bundle_id,
        attachment_id=attachment_id,
    )
    playback_request_id = str(uuid.uuid4())
    reservation = admission.reserve(before["byte_size"])
    try:
        phase_two_started = monotonic()
        try:
            body = (reader or R2ExactPrivateObjectReader()).read_exact(
                bucket=before["bucket"], object_key=before["object_key"],
                byte_size=before["byte_size"],
                expected_sha256=before["exact_bytes_sha256"],
                monotonic=monotonic,
            )
        except ConfidentMomentSourceMediaPolicyInvalid:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            # Provider/connect/read failures are externally retryable.  The
            # exact reservation is still released by the outer finally.
            raise ConfidentMomentUserReadRetry(
                ConfidentMomentUserReadRetry.code
            ) from error
        # D43 starts the buffer TTL when the exact-size read completes.  Hash
        # time consumes that TTL and also remains inside phase 2's 8s budget.
        buffer_completed_at = monotonic()
        if len(body) != before["byte_size"]:
            raise ConfidentMomentSourceMediaPolicyInvalid(
                ConfidentMomentSourceMediaPolicyInvalid.code
            )
        if sha256(body).hexdigest() != before["exact_bytes_sha256"]:
            raise ConfidentMomentSourceMediaPolicyInvalid(
                ConfidentMomentSourceMediaPolicyInvalid.code
            )
        if monotonic() - phase_two_started >= 8.0:
            raise ConfidentMomentUserReadRetry(
                ConfidentMomentUserReadRetry.code
            )

        last_retry: Exception | None = None
        authorization_consumed = False
        for attempt_number in (1, 2):
            remaining = BUFFER_TTL_SECONDS - (monotonic() - buffer_completed_at)
            if remaining < (
                DATABASE_PHASE_BUDGET_SECONDS + LOCAL_EMIT_BUDGET_SECONDS
            ):
                break
            try:
                authorization = authorize_emit(
                    before["authority_sha256"],
                    before["exact_bytes_sha256"],
                    playback_request_id,
                )
            except Exception as error:
                if "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED" not in str(error):
                    raise
                last_retry = error
                if attempt_number == 1:
                    sleep(jitter(0.025, 0.075))
                continue
            authorization_returned_at = monotonic()
            try:
                authorization_consumed = validate_and_consume_emit_authorization(
                    authorization,
                    playback_request_id=playback_request_id,
                    principal_id=principal_id,
                    bundle_id=bundle_id,
                    attachment_id=attachment_id,
                    authority_sha256=before["authority_sha256"],
                    buffered_body=body,
                    window_started_at=authorization_returned_at,
                    buffer_completed_at=buffer_completed_at,
                    monotonic=monotonic,
                    already_consumed=authorization_consumed,
                )
                return body, before["content_type"]
            except ConfidentMomentUserReadRetry as error:
                last_retry = error
                if attempt_number == 1:
                    sleep(jitter(0.025, 0.075))
                continue
        raise ConfidentMomentUserReadRetry(
            ConfidentMomentUserReadRetry.code
        ) from last_retry
    finally:
        admission.release(reservation)


_CORRELATION_BASE_KEYS = {
    "contract_version", "status", "bundle_id", "bundle_attachment_id",
    "offer_id", "correlation_sha256", "dataset_eligible",
}
_CORRELATION_AVAILABLE_KEYS = _CORRELATION_BASE_KEYS | {
    "feedback_response_binding_id", "n1_candidate_set_id",
    "authorization_check_id", "source_acquisition_receipt_id",
    "source_target_speaker_binding_id",
}


def validate_exercise_correlation(
    value: Any, *, bundle_id: str, attachment_id: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise RuntimeError("CONFIDENT_MOMENT_EXERCISE_CORRELATION_INVALID")
    status = value.get("status")
    expected_keys = (
        _CORRELATION_BASE_KEYS if status == "not_supplied"
        else _CORRELATION_AVAILABLE_KEYS if status == "available" else set()
    )
    if set(value) != expected_keys or (
        value.get("contract_version")
        != "confident-moment-exercise-correlation-v2"
        or value.get("bundle_id") != bundle_id
        or value.get("bundle_attachment_id") != attachment_id
        or value.get("dataset_eligible") is not False
        or not isinstance(value.get("correlation_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["correlation_sha256"]) is None
    ):
        raise RuntimeError("CONFIDENT_MOMENT_EXERCISE_CORRELATION_INVALID")
    if status == "not_supplied":
        if value.get("offer_id") is not None:
            raise RuntimeError("CONFIDENT_MOMENT_EXERCISE_CORRELATION_INVALID")
    else:
        for field in _CORRELATION_AVAILABLE_KEYS - {
            "contract_version", "status", "bundle_id",
            "bundle_attachment_id", "correlation_sha256", "dataset_eligible",
        }:
            raw = value.get(field)
            try:
                if not isinstance(raw, str) or str(uuid.UUID(raw)) != raw:
                    raise ValueError
            except (ValueError, AttributeError):
                raise RuntimeError(
                    "CONFIDENT_MOMENT_EXERCISE_CORRELATION_INVALID"
                ) from None
    return value
