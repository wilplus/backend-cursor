"""Application orchestration for one first-client practice submission.

The database owns authorization, idempotency, lineage, and state transitions.
This module owns only the ordered application workflow around R2 and the
transcription provider, keeping the HTTP route small and testable.
"""
from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.first_client_repository import FirstClientRepository
from services.mlc3_pilot_storage import (
    PracticeAudioR2Storage,
    ReservedObject,
    store_exact_object,
)


_SERVICE_NAMESPACE = uuid.UUID("af581641-d57a-41d2-bf22-4150329438fa")


class PracticeAttemptNotFound(Exception):
    """The requested practice session is not live for this principal."""


class PracticeAttemptUnavailable(Exception):
    """A fail-closed service boundary rejected or could not finish the flow."""


@dataclass(frozen=True)
class PracticeAttemptCommand:
    session_id: str
    principal_id: str
    owner_user_id: str
    idempotency_key: str
    render_instance_id: str
    content_identity_sha256: str
    capture_started_at: str
    capture_completed_at: str
    audio: bytes
    filename: str
    content_type: str
    recording_conditions: dict[str, Any]
    client_version: str | None


@dataclass(frozen=True)
class _StoredPractice:
    recovery_id: str
    exact_bytes_sha256: str
    recording_attempt_id: str
    audio_object_id: str
    attempt_index: int
    finalized: dict[str, Any]


@dataclass(frozen=True)
class _Transcription:
    run: dict[str, Any]
    output: dict[str, Any]


class PracticeAttemptOrchestrator:
    """Run the exact media → transcript → measurement → selection workflow."""

    def __init__(
        self,
        repository: FirstClientRepository,
        *,
        storage_factory: Callable[[], Any] = PracticeAudioR2Storage,
    ) -> None:
        self.repository = repository
        self.storage_factory = storage_factory

    @staticmethod
    def _extension(filename: str, content_type: str) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix and len(suffix) <= 8:
            return suffix
        return mimetypes.guess_extension(content_type) or ".audio"

    @staticmethod
    def _require(row: dict[str, Any] | None, code: str) -> dict[str, Any]:
        if row is None:
            raise PracticeAttemptUnavailable(code)
        return row

    def execute(self, command: PracticeAttemptCommand) -> dict[str, Any]:
        session = self.repository.resolve_exercise_practice_session_read(
            command.session_id, command.principal_id
        )
        if session is None:
            raise PracticeAttemptNotFound(command.session_id)

        stored = self._store_audio(command, session)
        self._record_capture_events(command, session, stored)
        transcription = self._transcribe(command, stored)
        attempt, duration_ms, pcm = self._attach_attempt(
            command, session, stored, transcription
        )
        validity, selection = self._measure_and_select(
            command, session, attempt, transcription, pcm
        )
        self._record_processed_event(
            command, session, attempt, validity, selection
        )
        playback_url = self._playback_url(command, attempt)
        owner_pair = (
            None
            if session.get("operation_mode") in {
                "cohort_service", "general_service"
            }
            else self._owner_pair(command, session, attempt, selection)
        )
        return self._response(
            attempt=attempt,
            duration_ms=duration_ms,
            playback_url=playback_url,
            validity=validity,
            selection=selection,
            owner_pair=owner_pair,
        )

    def _store_audio(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
    ) -> _StoredPractice:
        identity = (
            f"{command.principal_id}:{command.session_id}:"
            f"{command.idempotency_key}"
        )
        recording_id = str(uuid.uuid5(
            _SERVICE_NAMESPACE, f"{identity}:recording"
        ))
        recording_attempt_id = str(uuid.uuid5(
            _SERVICE_NAMESPACE, f"{identity}:attempt"
        ))
        audio_object_id = str(uuid.uuid5(
            _SERVICE_NAMESPACE, f"{identity}:audio"
        ))
        object_key = (
            f"mlc3-practice/{command.principal_id}/{command.session_id}/"
            f"{audio_object_id}{self._extension(command.filename, command.content_type)}"
        )
        finalized: dict[str, Any] = {}
        attempt_index: int | None = None

        def reserve(**media: Any) -> ReservedObject:
            nonlocal attempt_index
            row = self._require(
                self.repository.reserve_exercise_practice_service_upload({
                    "p_session_id": str(session["id"]),
                    "p_acquisition_principal_id": command.principal_id,
                    "p_recording_id": recording_id,
                    "p_object_key": object_key,
                    "p_byte_size": media["byte_size"],
                    "p_content_type": media["content_type"],
                    "p_intended_exact_bytes_sha256": media[
                        "exact_bytes_sha256"
                    ],
                    "p_idempotency_key": (
                        f"{command.idempotency_key}:upload"
                    ),
                    "p_ttl_seconds": 900,
                }),
                "PRACTICE_UPLOAD_RESERVATION_FAILED",
            )
            attempt_index = int(row["attempt_index"])
            return ReservedObject(
                recovery_id=str(row["id"]),
                bucket=str(row["bucket"]),
                object_key=str(row["object_key"]),
                exact_bytes_sha256=str(row["intended_exact_bytes_sha256"]),
                byte_size=int(row["byte_size"]),
                content_type=str(row["content_type"]),
                write_required=str(row.get("status") or "") == "write_started",
                attempt_index=attempt_index,
            )

        def acknowledge(reserved: ReservedObject) -> None:
            self._require(
                self.repository.ack_exercise_practice_service_upload({
                    "p_recovery_id": reserved.recovery_id,
                    "p_acquisition_principal_id": command.principal_id,
                    "p_exact_bytes_sha256": reserved.exact_bytes_sha256,
                    "p_byte_size": reserved.byte_size,
                    "p_idempotency_key": (
                        f"{command.idempotency_key}:upload-ack"
                    ),
                }),
                "PRACTICE_UPLOAD_ACK_FAILED",
            )

        def finalize(**media: Any) -> str:
            row = self._require(
                self.repository.finalize_exercise_practice_service_media({
                    "p_recovery_id": media["recovery"].recovery_id,
                    "p_acquisition_principal_id": command.principal_id,
                    "p_processing_recording_attempt_id": (
                        recording_attempt_id
                    ),
                    "p_processing_audio_object_id": audio_object_id,
                    "p_verification_method": media["verification_method"],
                    "p_idempotency_key": (
                        f"{command.idempotency_key}:media"
                    ),
                }),
                "PRACTICE_MEDIA_FINALIZATION_FAILED",
            )
            finalized.update(row)
            return str(row["processing_audio_object_id"])

        stored = store_exact_object(
            body=command.audio,
            content_type=command.content_type,
            reserve=reserve,
            finalize=finalize,
            storage=self.storage_factory(),
            record_write_started=lambda _reserved: None,
            record_write_acknowledged=acknowledge,
        )
        if attempt_index is None:
            raise PracticeAttemptUnavailable(
                "PRACTICE_ATTEMPT_INDEX_NOT_ALLOCATED"
            )
        return _StoredPractice(
            recovery_id=stored.recovery_id,
            exact_bytes_sha256=stored.exact_bytes_sha256,
            recording_attempt_id=recording_attempt_id,
            audio_object_id=audio_object_id,
            attempt_index=attempt_index,
            finalized=finalized,
        )

    def _event(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
        *,
        event_kind: str,
        occurred_at: str,
        attempt_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._require(
            self.repository.record_exercise_practice_service_event({
                "p_session_id": str(session["id"]),
                "p_acquisition_principal_id": command.principal_id,
                "p_recipient_user_id": command.owner_user_id,
                "p_attempt_id": attempt_id,
                "p_event_kind": event_kind,
                "p_render_instance_id": command.render_instance_id,
                "p_content_identity_sha256": (
                    command.content_identity_sha256
                ),
                "p_event_payload": payload,
                "p_occurred_at": occurred_at,
                "p_idempotency_key": (
                    f"{command.idempotency_key}:{event_kind}"
                ),
            }),
            f"PRACTICE_{event_kind.upper()}_EVENT_FAILED",
        )

    def _record_capture_events(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
        stored: _StoredPractice,
    ) -> None:
        payload = {"attempt_index": stored.attempt_index}
        for event_kind in ("capture_reserved", "capture_started"):
            self._event(
                command,
                session,
                event_kind=event_kind,
                occurred_at=command.capture_started_at,
                attempt_id=None,
                payload=payload,
            )
        self._event(
            command,
            session,
            event_kind="capture_completed",
            occurred_at=command.capture_completed_at,
            attempt_id=None,
            payload={
                **payload,
                "exact_bytes_sha256": stored.exact_bytes_sha256,
            },
        )

    def _transcribe(
        self,
        command: PracticeAttemptCommand,
        stored: _StoredPractice,
    ) -> _Transcription:
        from services.snippet_transcription import (
            TRANSCRIPTION_LANGUAGE_POLICY_VERSION,
            TRANSCRIPTION_MODEL_VERSION,
            TRANSCRIPTION_OUTPUT_SCHEMA_VERSION,
            TRANSCRIPTION_PROMPT_VERSION,
            TRANSCRIPTION_PROVIDER,
        )

        run = self.repository.authorize_exercise_practice_transcription({
            "p_recovery_id": stored.recovery_id,
            "p_acquisition_principal_id": command.principal_id,
            "p_processing_recording_attempt_id": (
                stored.recording_attempt_id
            ),
            "p_processing_audio_object_id": stored.audio_object_id,
            "p_practice_acquisition_receipt_id": stored.finalized[
                "practice_acquisition_receipt_id"
            ],
            "p_provider": TRANSCRIPTION_PROVIDER,
            "p_model_version": TRANSCRIPTION_MODEL_VERSION,
            "p_prompt_version": TRANSCRIPTION_PROMPT_VERSION,
            "p_language_policy_version": TRANSCRIPTION_LANGUAGE_POLICY_VERSION,
            "p_language_hint": None,
            "p_output_schema_version": TRANSCRIPTION_OUTPUT_SCHEMA_VERSION,
            "p_idempotency_key": (
                f"{command.idempotency_key}:transcription"
            ),
        })
        if run is None:
            self.repository.reconcile_exercise_practice_transcription_request({
                "p_recovery_id": stored.recovery_id,
                "p_acquisition_principal_id": command.principal_id,
                "p_authorization_idempotency_key": (
                    f"{command.idempotency_key}:transcription"
                ),
                "p_reconciliation_idempotency_key": (
                    f"{command.idempotency_key}:transcription-reconciliation"
                ),
            })
            raise PracticeAttemptUnavailable(
                "PRACTICE_TRANSCRIPTION_AUTHORIZATION_FAILED"
            )
        if run.get("status") == "finalized":
            output = run.get("normalized_output")
            if not isinstance(output, dict):
                raise PracticeAttemptUnavailable(
                    "PRACTICE_TRANSCRIPTION_OUTPUT_MISSING"
                )
            return _Transcription(run=run, output=output)
        return self._dispatch_transcription(command, run)

    def _dispatch_transcription(
        self,
        command: PracticeAttemptCommand,
        run: dict[str, Any],
    ) -> _Transcription:
        from services.snippet_transcription import (
            SnippetTranscriptionProviderError,
            transcribe_snippet_bytes,
        )

        if run.get("status") != "authorized":
            if run.get("status") == "dispatched":
                self.repository.reconcile_exercise_practice_transcription({
                    "p_run_id": str(run["id"]),
                    "p_acquisition_principal_id": command.principal_id,
                    "p_idempotency_key": (
                        f"{command.idempotency_key}:"
                        "transcription-reconciliation"
                    ),
                })
            raise PracticeAttemptUnavailable(
                "PRACTICE_TRANSCRIPTION_NOT_DISPATCHABLE"
            )
        run = self._require(
            self.repository.mark_exercise_practice_transcription_dispatched({
                "p_run_id": str(run["id"]),
                "p_acquisition_principal_id": command.principal_id,
                "p_idempotency_key": (
                    f"{command.idempotency_key}:transcription-dispatch"
                ),
            }),
            "PRACTICE_TRANSCRIPTION_DISPATCH_FAILED",
        )
        try:
            output = transcribe_snippet_bytes(
                command.audio,
                hint_filename=command.filename or "practice.audio",
                raise_on_provider_error=True,
            ) or {}
        except SnippetTranscriptionProviderError as error:
            self._finish_transcription(
                command,
                run,
                status="uncertain",
                output=None,
                provider_error=str(error)[:200],
            )
            raise PracticeAttemptUnavailable(
                "PRACTICE_TRANSCRIPTION_PROVIDER_FAILED"
            ) from error
        normalized = {
            "provider_response_id": output.get("provider_response_id"),
            "transcript": output.get("transcript"),
            "language": output.get("language"),
            "words": output.get("words") or [],
            "transcribed_duration_ms": output.get("transcribed_duration_ms"),
        }
        terminal = self._finish_transcription(
            command,
            run,
            status="finalized",
            output=normalized,
            provider_error=None,
        )
        if terminal is None or terminal.get("status") != "finalized":
            raise PracticeAttemptUnavailable(
                "PRACTICE_TRANSCRIPTION_FINALIZATION_FAILED"
            )
        return _Transcription(run=terminal, output=normalized)

    def _finish_transcription(
        self,
        command: PracticeAttemptCommand,
        run: dict[str, Any],
        *,
        status: str,
        output: dict[str, Any] | None,
        provider_error: str | None,
    ) -> dict[str, Any] | None:
        run_id = str(run["id"])
        terminal = self.repository.finalize_exercise_practice_transcription({
            "p_run_id": run_id,
            "p_acquisition_principal_id": command.principal_id,
            "p_terminal_status": status,
            "p_normalized_output": output,
            "p_provider_error_code": provider_error,
            "p_idempotency_key": (
                f"{command.idempotency_key}:transcription-result"
            ),
        })
        if terminal is not None:
            return terminal
        return self.repository.reconcile_exercise_practice_transcription({
            "p_run_id": run_id,
            "p_acquisition_principal_id": command.principal_id,
            "p_idempotency_key": (
                f"{command.idempotency_key}:transcription-reconciliation"
            ),
        })

    def _attach_attempt(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
        stored: _StoredPractice,
        transcription: _Transcription,
    ) -> tuple[dict[str, Any], int, Any]:
        from services.audio_metrics import SAMPLE_RATE, decode_audio_to_pcm

        pcm = decode_audio_to_pcm(command.audio)
        duration_ms = (
            int((len(pcm) / float(SAMPLE_RATE)) * 1000)
            if pcm is not None
            else int(transcription.output.get("transcribed_duration_ms") or 0)
        )
        if duration_ms < 1:
            raise ValueError("audio duration could not be verified")
        conditions = {
            **command.recording_conditions,
            "content_type": command.content_type,
            "client_version": command.client_version,
        }
        attempt = self._require(
            self.repository.attach_exercise_practice_service_attempt({
                "p_recovery_id": stored.recovery_id,
                "p_processing_recording_attempt_id": (
                    stored.recording_attempt_id
                ),
                "p_processing_audio_object_id": stored.audio_object_id,
                "p_practice_acquisition_receipt_id": stored.finalized[
                    "practice_acquisition_receipt_id"
                ],
                "p_transcription_run_id": str(transcription.run["id"]),
                "p_exact_passage": str(session["exact_passage"]),
                "p_duration_ms": duration_ms,
                "p_capture_started_at": command.capture_started_at,
                "p_capture_completed_at": command.capture_completed_at,
                "p_recording_conditions": conditions,
                "p_idempotency_key": f"{command.idempotency_key}:attempt",
            }),
            "PRACTICE_ATTEMPT_ATTACHMENT_FAILED",
        )
        return attempt, duration_ms, pcm

    def _measure_and_select(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
        attempt: dict[str, Any],
        transcription: _Transcription,
        pcm: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from services.rushed_phrase_endings_n1 import (
            EXTRACTOR_VERSION,
            FEATURE_SCHEMA_VERSION,
            VALIDITY_CONTRACT_VERSION,
            extract_rushed_phrase_endings_n1,
        )

        raw, safeguards, reasons = extract_rushed_phrase_endings_n1(
            exact_passage=str(session["exact_passage"]),
            transcript=str(transcription.output.get("transcript") or "").strip(),
            words=transcription.output.get("words") or [],
            pcm=pcm,
            language=transcription.output.get("language"),
        )
        measurement = self._require(
            self.repository.record_exercise_practice_service_measurement({
                "p_attempt_id": str(attempt["id"]),
                "p_measurement_revision": 1,
                "p_extractor_version": EXTRACTOR_VERSION,
                "p_feature_schema_version": FEATURE_SCHEMA_VERSION,
                "p_raw_measurements": raw,
                "p_safeguards": safeguards,
                "p_idempotency_key": (
                    f"{command.idempotency_key}:measurement"
                ),
            }),
            "PRACTICE_MEASUREMENT_FAILED",
        )
        validity = self._require(
            self.repository.record_exercise_practice_service_validity({
                "p_attempt_id": str(attempt["id"]),
                "p_measurement_revision_id": str(measurement["id"]),
                "p_baseline_revision": int(session["baseline_revision"]),
                "p_validity": "valid" if not reasons else "invalid",
                "p_reason_codes": reasons,
                "p_validity_contract_version": VALIDITY_CONTRACT_VERSION,
                "p_idempotency_key": f"{command.idempotency_key}:validity",
            }),
            "PRACTICE_VALIDITY_FAILED",
        )
        selection = self._require(
            self.repository.freeze_exercise_practice_service_selection({
                "p_session_id": str(session["id"]),
                "p_acquisition_principal_id": command.principal_id,
                "p_baseline_revision": int(session["baseline_revision"]),
                "p_revision": int(attempt["attempt_index"]),
                "p_idempotency_key": f"{command.idempotency_key}:selection",
            }),
            "PRACTICE_SELECTION_FAILED",
        )
        return validity, selection

    def _record_processed_event(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
        attempt: dict[str, Any],
        validity: dict[str, Any],
        selection: dict[str, Any],
    ) -> None:
        self._event(
            command,
            session,
            event_kind="attempt_processed",
            occurred_at=command.capture_completed_at,
            attempt_id=str(attempt["id"]),
            payload={
                "validity": validity["validity"],
                "selection_state": selection["selection_state"],
            },
        )

    def _playback_url(
        self,
        command: PracticeAttemptCommand,
        attempt: dict[str, Any],
    ) -> str:
        # The browser never receives an R2 credential or presigned URL. The
        # authenticated route performs fresh authority/deletion checks before
        # and after reading the exact bytes.
        return (
            f"/api/v2/user/mlc3/practice-attempts/{attempt['id']}/playback"
        )

    def _owner_pair(
        self,
        command: PracticeAttemptCommand,
        session: dict[str, Any],
        attempt: dict[str, Any],
        selection: dict[str, Any],
    ) -> dict[str, Any] | None:
        if selection.get("selection_state") != "selected_first_valid":
            return None
        if str(selection.get("selected_attempt_id") or "") != str(attempt["id"]):
            return None
        pair = self._require(
            self.repository.freeze_exercise_service_pair({
                "p_practice_session_id": str(session["id"]),
                "p_acquisition_principal_id": command.principal_id,
                "p_selection_revision_id": str(selection["id"]),
                "p_comparison_revision": int(selection["revision"]),
                "p_idempotency_key": f"{command.idempotency_key}:pair",
            }),
            "PRACTICE_PAIR_FREEZE_FAILED",
        )
        assignment = self._require(
            self.repository.assign_exercise_service_owner_pair({
                "p_pair_revision_id": str(pair["id"]),
                "p_acquisition_principal_id": command.principal_id,
                "p_idempotency_key": (
                    f"{command.idempotency_key}:owner-pair"
                ),
            }),
            "PRACTICE_OWNER_PAIR_FAILED",
        )
        return {
            "pair_revision_id": str(pair["id"]),
            "pair_assignment_id": str(assignment["id"]),
            "left_clip": assignment["left_clip"],
            "right_clip": assignment["right_clip"],
            "answer_taxonomy_version": (
                "paired-listening-preference-five-state-v1"
            ),
        }

    @staticmethod
    def _response(
        *,
        attempt: dict[str, Any],
        duration_ms: int,
        playback_url: str,
        validity: dict[str, Any],
        selection: dict[str, Any],
        owner_pair: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "attempt_id": str(attempt["id"]),
            "attempt_index": attempt["attempt_index"],
            "audio_ref": playback_url,
            "duration_ms": duration_ms,
            "transcript_state": attempt["transcript_state"],
            "validity": validity["validity"],
            "reason_codes": validity["reason_codes"],
            "selection_state": selection["selection_state"],
            "selected_attempt_id": selection.get("selected_attempt_id"),
            "owner_pair": owner_pair,
            "speaker_confirmation_required": (
                owner_pair is None
                and selection.get("selection_state") == "selected_first_valid"
            ),
            "serves_user": False,
            "dataset_eligible": False,
        }
