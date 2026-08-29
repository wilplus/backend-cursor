"""Typed provider adapter for Willab user data.

No protected recording module should instantiate a provider SDK directly.
The adapter obtains a short-lived database permit immediately before the call
and records its terminal outcome without storing raw user content in metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
from io import BytesIO
import threading
import uuid
from typing import Any, Mapping

from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)


@dataclass(frozen=True)
class ProviderCoordinates:
    acquisition_principal_id: str
    take_id: str | None
    recording_id: str | None


@dataclass
class _ProtectedCallScope:
    adapter: "AuthorizedProviderAdapter"
    idempotency_prefix: str
    _counts: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def next_key(self, surface: str) -> str:
        safe_surface = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in str(surface or "unknown")
        )[:80]
        with self._lock:
            ordinal = self._counts.get(safe_surface, 0) + 1
            self._counts[safe_surface] = ordinal
        return f"{self.idempotency_prefix}:generation:{safe_surface}:{ordinal}"


_protected_call_scope: ContextVar[_ProtectedCallScope | None] = ContextVar(
    "willab_protected_provider_scope", default=None,
)


@contextmanager
def protected_provider_scope(
    adapter: "AuthorizedProviderAdapter", *, idempotency_prefix: str,
):
    """Bind one accepted Take to every shared LLM call below it.

    The context is copied by ``services.parallel`` into its bounded worker
    threads.  Non-user/admin jobs do not enter this scope and retain their
    existing provider behavior.
    """
    token = _protected_call_scope.set(_ProtectedCallScope(
        adapter=adapter,
        idempotency_prefix=str(idempotency_prefix),
    ))
    try:
        yield
    finally:
        _protected_call_scope.reset(token)


def authorize_protected_generation(surface: str) -> tuple[
    ProcessingAuthorizationService | None, str | None,
]:
    """Issue the per-call permit for a protected language-model operation."""
    scope = _protected_call_scope.get()
    if scope is None:
        return None, None
    permit = scope.adapter.authorize_operation(
        "feedback_generation",
        manifest={
            "content": ["bounded_transcript_context", "bounded_prompt_context"],
            "purpose": "recording_feedback",
            "surface": str(surface),
        },
        idempotency_key=scope.next_key(surface),
    )
    permit_id = str((permit or {}).get("permit_id") or "") or None
    scope.adapter.authorization.record_provider_event(permit_id, "started")
    return scope.adapter.authorization, permit_id


class AuthorizedProviderAdapter:
    def __init__(
        self, database: Any, coordinates: ProviderCoordinates,
        *, authorization: ProcessingAuthorizationService | None = None,
    ) -> None:
        self.database = database
        self.coordinates = coordinates
        self.authorization = authorization or ProcessingAuthorizationService(database)

    def transcribe_audio(
        self, audio_bytes: bytes, filename: str, *,
        vocabulary: list | None = None, language: str | None = None,
        usage_surface: str, usage_user_id: str | None,
        usage_session_id: str,
    ) -> dict | None:
        permit = self.authorization.issue_provider_permit(
            acquisition_principal_id=self.coordinates.acquisition_principal_id,
            take_id=self.coordinates.take_id,
            recording_id=self.coordinates.recording_id,
            provider="openai",
            operation_kind="transcription",
            minimum_data_manifest={
                "content": ["audio_bytes", "bounded_vocabulary", "language_hint"],
                "purpose": "transcription_feedback",
            },
            idempotency_key=(
                f"openai:transcription:{self.coordinates.take_id}:"
                f"{self.coordinates.recording_id}:{uuid.uuid4()}"
            ),
        )
        permit_id = str((permit or {}).get("permit_id") or "") or None
        self.authorization.record_provider_event(permit_id, "started")
        try:
            from services.openai_service import OpenAIService

            service = OpenAIService()
            if not service.client:
                if not self.authorization.enforced:
                    return None
                raise ProcessingAuthorizationError(
                    "PROVIDER_UNAVAILABLE", "The transcription provider is unavailable.", 503
                )
            result = service.transcribe_audio(
                BytesIO(audio_bytes), filename,
                vocabulary=vocabulary, language=language,
                usage_surface=usage_surface,
                usage_user_id=usage_user_id,
                usage_session_id=usage_session_id,
            ) or {}
            self.authorization.record_provider_event(
                permit_id, "completed",
                metadata={"result_kind": "transcription"},
            )
            return result
        except Exception as error:
            self.authorization.record_provider_event(
                permit_id, "failed", error_code=type(error).__name__,
            )
            raise

    def authorize_operation(
        self, operation_kind: str, *, manifest: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict | None:
        """Permit boundary for generation/coach operations implemented by an
        existing domain service. The caller still performs the operation, but
        it cannot begin without this typed permit."""
        return self.authorization.issue_provider_permit(
            acquisition_principal_id=self.coordinates.acquisition_principal_id,
            take_id=self.coordinates.take_id,
            recording_id=self.coordinates.recording_id,
            provider=(
                "cloudflare_r2" if operation_kind == "audio_download"
                else "willab_coach" if operation_kind == "coach_delivery"
                else "openai"
            ),
            operation_kind=operation_kind,
            minimum_data_manifest=manifest,
            idempotency_key=idempotency_key,
        )

    def download_audio(
        self, *, storage_provider: str, bucket: str, object_key: str,
        idempotency_key: str
    ) -> bytes:
        permit = self.authorize_operation(
            "audio_download",
            manifest={"content": ["immutable_audio_object"],
                      "purpose": "recording_voice_processing"},
            idempotency_key=idempotency_key,
        )
        permit_id = str((permit or {}).get("permit_id") or "") or None
        self.authorization.record_provider_event(permit_id, "started")
        try:
            from services.lab_audio_storage import get_exact_storage_object_bytes

            data = get_exact_storage_object_bytes(
                object_key,
                bucket=bucket,
                storage_provider=storage_provider,
            )
            if not data:
                raise FileNotFoundError("authorized audio object is empty")
            self.authorization.record_provider_event(
                permit_id, "completed", metadata={"result_kind": "audio_bytes"},
            )
            return data
        except Exception as error:
            self.authorization.record_provider_event(
                permit_id, "failed", error_code=type(error).__name__,
            )
            raise
