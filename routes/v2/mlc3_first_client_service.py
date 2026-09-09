"""Allowlisted first-client exercise loop.

Every endpoint is hidden behind authentication, the backend master switch,
the exact acquisition-principal allowlist, and the database service contract.
Dataset, training, evaluation, and promotion operations do not exist here.
"""
from __future__ import annotations

import json
import mimetypes
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import jsonify, request

from auth import require_auth
from config import Config
from routes.phase2_guard import mlc3_pilot_required
from routes.v2.blueprint import v2_bp
from services.coach_guidance_delivery import require_audio_upload
from services.coach_video_storage import presigned_get_coach_object_r2
from services.db import db
from services.mlc3_pilot_storage import (
    PracticeAudioR2Storage,
    ReservedObject,
    store_exact_object,
)

_SERVICE_NAMESPACE = uuid.UUID("af581641-d57a-41d2-bf22-4150329438fa")
_SERVICE_RESPONSES = {
    "confident_yes",
    "confident_in_between",
    "confident_no",
    "confident_not_sure",
    "confident_audio_unclear",
}
_OFFER_EVENTS = {
    "render_confirmed",
    "playback_started",
    "playback_completed",
}
_PRACTICE_EVENTS = _OFFER_EVENTS


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field} must be a UUID") from error


def _sha256(value: Any, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a SHA-256")
    return normalized


def _idempotency_key() -> str:
    value = str(request.headers.get("Idempotency-Key") or "").strip()
    if not 1 <= len(value) <= 200:
        raise ValueError("Idempotency-Key is required")
    return value


def _body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise TypeError("JSON object required")
    return value


def _principal_id() -> str:
    return _uuid(getattr(request, "mlc3_principal_id", None), "principal_id")


def _error(error: ValueError | TypeError):
    return jsonify({"code": "INVALID_INPUT", "error": str(error)}), 400


def _service_unavailable():
    return jsonify({"code": "MLC3_SERVICE_NOT_AVAILABLE"}), 409


def _rpc_time(value: Any, field: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"{field} must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _event_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("event_payload must be an object")
    return value


def _offer_public_payload(offer: dict, version: dict | None = None) -> dict:
    payload = {
        "id": str(offer["id"]),
        "outcome": offer["outcome"],
        "selected_exercise_version_id": offer.get(
            "selected_exercise_version_id"
        ),
        "candidate_count": offer.get("candidate_count"),
        "eligible_count": offer.get("eligible_count"),
        "matching_policy_version": offer.get("matching_policy_version"),
        "serves_user": True,
        "dataset_eligible": False,
    }
    if version:
        media = version.get("media") or {}
        media_url = presigned_get_coach_object_r2(
            str(media.get("bucket") or ""),
            str(media.get("object_key") or ""),
            expires_in=900,
        )
        payload["exercise"] = {
            "version_id": str(version["id"]),
            "instruction_text": version["instruction_text"],
            "content_identity_sha256": version["version_sha256"],
            "media_url": media_url,
            "media_content_type": media.get("content_type"),
        }
    return payload


@v2_bp.post("/user/mlc3/feedback/render")
@require_auth
@mlc3_pilot_required
def v2_mlc3_feedback_render():
    try:
        body = _body()
        row = db.ack_feedback_v3_service_render({
            "p_acquisition_principal_id": _principal_id(),
            "p_owner_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_membership_id": _uuid(body.get("membership_id"), "membership_id"),
            "p_candidate_id": _uuid(body.get("candidate_id"), "candidate_id"),
            "p_feedback_exposure_id": _uuid(
                body.get("feedback_exposure_id"), "feedback_exposure_id"
            ),
            "p_render_instance_id": _uuid(
                body.get("render_instance_id"), "render_instance_id"
            ),
            "p_content_identity_sha256": _sha256(
                body.get("content_identity_sha256"),
                "content_identity_sha256",
            ),
            "p_rendered_at": _rpc_time(body.get("rendered_at"), "rendered_at"),
            "p_client_version": str(body.get("client_version") or "").strip(),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({"render_receipt_id": row["id"]}), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/feedback/respond")
@require_auth
@mlc3_pilot_required
def v2_mlc3_feedback_respond():
    try:
        body = _body()
        response = str(body.get("response") or "")
        if response not in _SERVICE_RESPONSES:
            raise ValueError("response is not in the five-state taxonomy")
        row = db.record_feedback_v3_service_response({
            "p_project_id": _uuid(body.get("project_id"), "project_id"),
            "p_take_id": _uuid(body.get("take_id"), "take_id"),
            "p_acquisition_principal_id": _principal_id(),
            "p_owner_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_feedback_membership_id": _uuid(
                body.get("membership_id"), "membership_id"
            ),
            "p_candidate_id": _uuid(body.get("candidate_id"), "candidate_id"),
            "p_feedback_exposure_id": _uuid(
                body.get("feedback_exposure_id"), "feedback_exposure_id"
            ),
            "p_render_receipt_id": _uuid(
                body.get("render_receipt_id"), "render_receipt_id"
            ),
            "p_response": response,
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({
            "response_binding_id": row["id"],
            "response": row["response"],
            "exercise_offer_allowed": response != "confident_audio_unclear",
        }), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/exercise-offers")
@require_auth
@mlc3_pilot_required
def v2_mlc3_create_exercise_offer():
    try:
        body = _body()
        row = db.freeze_exercise_service_offer_v2({
            "p_acquisition_principal_id": _principal_id(),
            "p_feedback_response_binding_id": _uuid(
                body.get("feedback_response_binding_id"),
                "feedback_response_binding_id",
            ),
            "p_n1_candidate_set_id": _uuid(
                body.get("n1_candidate_set_id"), "n1_candidate_set_id"
            ),
            "p_authorization_check_id": _uuid(
                body.get("authorization_check_id"), "authorization_check_id"
            ),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify(_offer_public_payload(row)), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.get("/user/mlc3/exercise-offers/<offer_id>")
@require_auth
@mlc3_pilot_required
def v2_mlc3_get_exercise_offer(offer_id: str):
    try:
        principal = _principal_id()
        resolved = db.resolve_exercise_service_offer_read(
            _uuid(offer_id, "offer_id"), principal,
        )
        if resolved is None:
            return jsonify({"code": "NOT_FOUND"}), 404
        offer = resolved["offer"]
        version = resolved.get("exercise_version")
        version_id = offer.get("selected_exercise_version_id")
        if version_id:
            media = resolved.get("media")
            if version is None or media is None:
                return _service_unavailable()
            version = {**version, "media": media}
            content_hash = _sha256(
                version.get("version_sha256"), "content_identity_sha256"
            )
            event = db.record_exercise_offer_service_event({
                "p_offer_id": str(offer["id"]),
                "p_acquisition_principal_id": principal,
                "p_recipient_user_id": _uuid(
                    getattr(request, "user_id", None), "owner_user_id"
                ),
                "p_event_kind": "delivery_prepared",
                "p_render_instance_id": None,
                "p_content_identity_sha256": content_hash,
                "p_event_payload": {"exercise_version_id": str(version_id)},
                "p_occurred_at": datetime.now(UTC).isoformat(),
                "p_idempotency_key": _idempotency_key(),
            })
            if event is None:
                return _service_unavailable()
        return jsonify(_offer_public_payload(offer, version)), 200
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/exercise-offers/<offer_id>/events")
@require_auth
@mlc3_pilot_required
def v2_mlc3_exercise_offer_event(offer_id: str):
    try:
        body = _body()
        event_kind = str(body.get("event_kind") or "")
        if event_kind not in _OFFER_EVENTS:
            raise ValueError("event_kind is not a client offer event")
        row = db.record_exercise_offer_service_event({
            "p_offer_id": _uuid(offer_id, "offer_id"),
            "p_acquisition_principal_id": _principal_id(),
            "p_recipient_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_event_kind": event_kind,
            "p_render_instance_id": _uuid(
                body.get("render_instance_id"), "render_instance_id"
            ),
            "p_content_identity_sha256": _sha256(
                body.get("content_identity_sha256"),
                "content_identity_sha256",
            ),
            "p_event_payload": _event_payload(body.get("event_payload")),
            "p_occurred_at": _rpc_time(body.get("occurred_at"), "occurred_at"),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({"event_id": row["id"], "event_kind": event_kind}), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/exercise-offers/<offer_id>/practice-sessions")
@require_auth
@mlc3_pilot_required
def v2_mlc3_create_practice_session(offer_id: str):
    try:
        body = _body()
        row = db.create_exercise_practice_service_session({
            "p_offer_id": _uuid(offer_id, "offer_id"),
            "p_acquisition_principal_id": _principal_id(),
            "p_source_acquisition_receipt_id": _uuid(
                body.get("source_acquisition_receipt_id"),
                "source_acquisition_receipt_id",
            ),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({"practice_session_id": row["id"]}), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.get("/user/mlc3/practice-sessions/<session_id>")
@require_auth
@mlc3_pilot_required
def v2_mlc3_get_practice_session(session_id: str):
    try:
        principal = _principal_id()
        row = db.resolve_exercise_practice_session_read(
            _uuid(session_id, "session_id"), principal
        )
        if row is None:
            return jsonify({"code": "NOT_FOUND"}), 404
        content_hash = _sha256(row.get("service_identity_sha256"), "content_identity")
        event = db.record_exercise_practice_service_event({
            "p_session_id": str(row["id"]),
            "p_acquisition_principal_id": principal,
            "p_recipient_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_attempt_id": None,
            "p_event_kind": "delivery_prepared",
            "p_render_instance_id": None,
            "p_content_identity_sha256": content_hash,
            "p_event_payload": {"source_offer_id": str(row["source_offer_id"])},
            "p_occurred_at": datetime.now(UTC).isoformat(),
            "p_idempotency_key": _idempotency_key(),
        })
        if event is None:
            return _service_unavailable()
        return jsonify({
            "id": str(row["id"]),
            "exact_passage": row["exact_passage"],
            "source_offer_id": str(row["source_offer_id"]),
            "exercise_version_id": str(row["exercise_version_id"]),
            "content_identity_sha256": content_hash,
            "next_attempt_index": int(row["next_attempt_index"]),
            "state": row["state"],
            "serves_user": True,
            "dataset_eligible": False,
        }), 200
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/practice-sessions/<session_id>/events")
@require_auth
@mlc3_pilot_required
def v2_mlc3_practice_event(session_id: str):
    try:
        body = _body()
        event_kind = str(body.get("event_kind") or "")
        if event_kind not in _PRACTICE_EVENTS:
            raise ValueError("event_kind is not a client practice event")
        row = db.record_exercise_practice_service_event({
            "p_session_id": _uuid(session_id, "session_id"),
            "p_acquisition_principal_id": _principal_id(),
            "p_recipient_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_attempt_id": None,
            "p_event_kind": event_kind,
            "p_render_instance_id": _uuid(
                body.get("render_instance_id"), "render_instance_id"
            ),
            "p_content_identity_sha256": _sha256(
                body.get("content_identity_sha256"),
                "content_identity_sha256",
            ),
            "p_event_payload": _event_payload(body.get("event_payload")),
            "p_occurred_at": _rpc_time(body.get("occurred_at"), "occurred_at"),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({"event_id": row["id"], "event_kind": event_kind}), 201
    except (TypeError, ValueError) as error:
        return _error(error)


def _extension(filename: str, content_type: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix and len(suffix) <= 8:
        return suffix
    return mimetypes.guess_extension(content_type) or ".audio"


@v2_bp.post("/user/mlc3/practice-sessions/<session_id>/attempts")
@require_auth
@mlc3_pilot_required
def v2_mlc3_practice_attempt(session_id: str):
    try:
        principal = _principal_id()
        session = db.resolve_exercise_practice_session_read(
            _uuid(session_id, "session_id"), principal
        )
        if session is None:
            return jsonify({"code": "NOT_FOUND"}), 404
        upload = request.files.get("audio")
        if upload is None:
            raise ValueError("audio is required")
        audio = upload.read(Config.MLC3_PILOT_MAX_AUDIO_MB * 1024 * 1024 + 1)
        content_type = require_audio_upload(
            body=audio,
            content_type=upload.mimetype or "",
            max_bytes=Config.MLC3_PILOT_MAX_AUDIO_MB * 1024 * 1024,
        )
        idempotency = _idempotency_key()
        render_instance = _uuid(
            request.form.get("render_instance_id"), "render_instance_id"
        )
        content_hash = _sha256(
            request.form.get("content_identity_sha256"),
            "content_identity_sha256",
        )
        capture_started_at = _rpc_time(
            request.form.get("capture_started_at"), "capture_started_at"
        )
        capture_completed_at = _rpc_time(
            request.form.get("capture_completed_at"), "capture_completed_at"
        )
        recording_id = str(uuid.uuid5(
            _SERVICE_NAMESPACE, f"{principal}:{session_id}:{idempotency}:recording"
        ))
        recording_attempt_id = str(uuid.uuid5(
            _SERVICE_NAMESPACE, f"{principal}:{session_id}:{idempotency}:attempt"
        ))
        audio_object_id = str(uuid.uuid5(
            _SERVICE_NAMESPACE, f"{principal}:{session_id}:{idempotency}:audio"
        ))
        object_key = (
            f"mlc3-practice/{principal}/{session_id}/"
            f"{audio_object_id}{_extension(upload.filename or '', content_type)}"
        )
        finalized: dict[str, Any] = {}
        allocated_attempt_index: int | None = None

        def reserve(**media: Any) -> ReservedObject:
            nonlocal allocated_attempt_index
            row = db.reserve_exercise_practice_service_upload({
                "p_session_id": str(session["id"]),
                "p_acquisition_principal_id": principal,
                "p_recording_id": recording_id,
                "p_object_key": object_key,
                "p_byte_size": media["byte_size"],
                "p_content_type": media["content_type"],
                "p_intended_exact_bytes_sha256": media["exact_bytes_sha256"],
                "p_idempotency_key": f"{idempotency}:upload",
                "p_ttl_seconds": 900,
            })
            if row is None:
                raise RuntimeError("PRACTICE_UPLOAD_RESERVATION_FAILED")
            allocated_attempt_index = int(row["attempt_index"])
            return ReservedObject(
                recovery_id=str(row["id"]),
                bucket=str(row["bucket"]),
                object_key=str(row["object_key"]),
                exact_bytes_sha256=str(row["intended_exact_bytes_sha256"]),
                byte_size=int(row["byte_size"]),
                content_type=str(row["content_type"]),
                write_required=str(row.get("status") or "") == "write_started",
                attempt_index=allocated_attempt_index,
            )

        def acknowledge(reserved: ReservedObject) -> None:
            row = db.ack_exercise_practice_service_upload({
                "p_recovery_id": reserved.recovery_id,
                "p_acquisition_principal_id": principal,
                "p_exact_bytes_sha256": reserved.exact_bytes_sha256,
                "p_byte_size": reserved.byte_size,
                "p_idempotency_key": f"{idempotency}:upload-ack",
            })
            if row is None:
                raise RuntimeError("PRACTICE_UPLOAD_ACK_FAILED")

        def finalize(**media: Any) -> str:
            row = db.finalize_exercise_practice_service_media({
                "p_recovery_id": media["recovery"].recovery_id,
                "p_acquisition_principal_id": principal,
                "p_processing_recording_attempt_id": recording_attempt_id,
                "p_processing_audio_object_id": audio_object_id,
                "p_verification_method": media["verification_method"],
                "p_idempotency_key": f"{idempotency}:media",
            })
            if row is None:
                raise RuntimeError("PRACTICE_MEDIA_FINALIZATION_FAILED")
            finalized.update(row)
            return str(row["processing_audio_object_id"])

        stored = store_exact_object(
            body=audio,
            content_type=content_type,
            reserve=reserve,
            finalize=finalize,
            storage=PracticeAudioR2Storage(),
            record_write_started=lambda _reserved: None,
            record_write_acknowledged=acknowledge,
        )
        if allocated_attempt_index is None:
            raise RuntimeError("PRACTICE_ATTEMPT_INDEX_NOT_ALLOCATED")
        attempt_index = allocated_attempt_index
        for event_kind, occurred_at in (
            ("capture_reserved", capture_started_at),
            ("capture_started", capture_started_at),
        ):
            event = db.record_exercise_practice_service_event({
                "p_session_id": str(session["id"]),
                "p_acquisition_principal_id": principal,
                "p_recipient_user_id": _uuid(
                    getattr(request, "user_id", None), "owner_user_id"
                ),
                "p_attempt_id": None,
                "p_event_kind": event_kind,
                "p_render_instance_id": render_instance,
                "p_content_identity_sha256": content_hash,
                "p_event_payload": {"attempt_index": attempt_index},
                "p_occurred_at": occurred_at,
                "p_idempotency_key": f"{idempotency}:{event_kind}",
            })
            if event is None:
                return _service_unavailable()
        completed_event = db.record_exercise_practice_service_event({
            "p_session_id": str(session["id"]),
            "p_acquisition_principal_id": principal,
            "p_recipient_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_attempt_id": None,
            "p_event_kind": "capture_completed",
            "p_render_instance_id": render_instance,
            "p_content_identity_sha256": content_hash,
            "p_event_payload": {
                "attempt_index": attempt_index,
                "exact_bytes_sha256": stored.exact_bytes_sha256,
            },
            "p_occurred_at": capture_completed_at,
            "p_idempotency_key": f"{idempotency}:capture_completed",
        })
        if completed_event is None:
            return _service_unavailable()

        from services.audio_metrics import SAMPLE_RATE, decode_audio_to_pcm
        from services.rushed_phrase_endings_n1 import (
            EXTRACTOR_VERSION,
            FEATURE_SCHEMA_VERSION,
            VALIDITY_CONTRACT_VERSION,
            extract_rushed_phrase_endings_n1,
        )
        from services.snippet_transcription import (
            TRANSCRIPTION_LANGUAGE_POLICY_VERSION,
            TRANSCRIPTION_MODEL_VERSION,
            TRANSCRIPTION_OUTPUT_SCHEMA_VERSION,
            TRANSCRIPTION_PROMPT_VERSION,
            TRANSCRIPTION_PROVIDER,
            SnippetTranscriptionProviderError,
            transcribe_snippet_bytes,
        )

        transcription_run = db.authorize_exercise_practice_transcription({
            "p_recovery_id": stored.recovery_id,
            "p_acquisition_principal_id": principal,
            "p_processing_recording_attempt_id": recording_attempt_id,
            "p_processing_audio_object_id": audio_object_id,
            "p_practice_acquisition_receipt_id": finalized[
                "practice_acquisition_receipt_id"
            ],
            "p_provider": TRANSCRIPTION_PROVIDER,
            "p_model_version": TRANSCRIPTION_MODEL_VERSION,
            "p_prompt_version": TRANSCRIPTION_PROMPT_VERSION,
            "p_language_policy_version": (
                TRANSCRIPTION_LANGUAGE_POLICY_VERSION
            ),
            "p_language_hint": None,
            "p_output_schema_version": TRANSCRIPTION_OUTPUT_SCHEMA_VERSION,
            "p_idempotency_key": f"{idempotency}:transcription",
        })
        if transcription_run is None:
            # If authorization itself was already committed on an earlier
            # delivery, this request-identity recovery can close its unresolved
            # dispatch even after authority was withdrawn.  It can only write
            # sanitized terminal provenance.
            db.reconcile_exercise_practice_transcription_request({
                "p_recovery_id": stored.recovery_id,
                "p_acquisition_principal_id": principal,
                "p_authorization_idempotency_key": (
                    f"{idempotency}:transcription"
                ),
                "p_reconciliation_idempotency_key": (
                    f"{idempotency}:transcription-reconciliation"
                ),
            })
            return _service_unavailable()
        transcribed: dict[str, Any]
        if transcription_run.get("status") == "finalized":
            # A response can be lost after provider finalization but before the
            # attempt and measurements are attached. Reuse only the immutable
            # canonical output; never dispatch the provider a second time.
            canonical_output = transcription_run.get("normalized_output")
            if not isinstance(canonical_output, dict):
                return _service_unavailable()
            transcribed = canonical_output
        else:
            # A committed dispatch is never sent to the provider twice. A
            # retry closes an unresolved prior dispatch with sanitized
            # provenance; other terminal states create no attempt.
            if transcription_run.get("status") != "authorized":
                if transcription_run.get("status") == "dispatched":
                    db.reconcile_exercise_practice_transcription({
                        "p_run_id": str(transcription_run["id"]),
                        "p_acquisition_principal_id": principal,
                        "p_idempotency_key": (
                            f"{idempotency}:transcription-reconciliation"
                        ),
                    })
                return _service_unavailable()
            transcription_run = (
                db.mark_exercise_practice_transcription_dispatched({
                    "p_run_id": str(transcription_run["id"]),
                    "p_acquisition_principal_id": principal,
                    "p_idempotency_key": (
                        f"{idempotency}:transcription-dispatch"
                    ),
                })
            )
            if transcription_run is None:
                return _service_unavailable()
            transcription_run_id = str(transcription_run["id"])

            def finalize_or_reconcile_transcription(
                terminal_payload: dict[str, Any],
            ) -> dict[str, Any] | None:
                terminal = db.finalize_exercise_practice_transcription(
                    terminal_payload
                )
                if terminal is not None:
                    return terminal
                return db.reconcile_exercise_practice_transcription({
                    "p_run_id": transcription_run_id,
                    "p_acquisition_principal_id": principal,
                    "p_idempotency_key": (
                        f"{idempotency}:transcription-reconciliation"
                    ),
                })
            try:
                transcribed = transcribe_snippet_bytes(
                    audio,
                    hint_filename=upload.filename or "practice.audio",
                    raise_on_provider_error=True,
                ) or {}
            except SnippetTranscriptionProviderError as error:
                finalize_or_reconcile_transcription({
                    "p_run_id": transcription_run_id,
                    "p_acquisition_principal_id": principal,
                    "p_terminal_status": "uncertain",
                    "p_normalized_output": None,
                    "p_provider_error_code": str(error)[:200],
                    "p_idempotency_key": (
                        f"{idempotency}:transcription-result"
                    ),
                })
                return _service_unavailable()
            normalized_transcription = {
                "provider_response_id": transcribed.get(
                    "provider_response_id"
                ),
                "transcript": transcribed.get("transcript"),
                "language": transcribed.get("language"),
                "words": transcribed.get("words") or [],
                "transcribed_duration_ms": transcribed.get(
                    "transcribed_duration_ms"
                ),
            }
            transcription_run = finalize_or_reconcile_transcription({
                "p_run_id": transcription_run_id,
                "p_acquisition_principal_id": principal,
                "p_terminal_status": "finalized",
                "p_normalized_output": normalized_transcription,
                "p_provider_error_code": None,
                "p_idempotency_key": f"{idempotency}:transcription-result",
            })
            if (
                transcription_run is None
                or transcription_run.get("status") != "finalized"
            ):
                return _service_unavailable()
        transcript = str((transcribed or {}).get("transcript") or "").strip()
        words = (transcribed or {}).get("words") or []
        pcm = decode_audio_to_pcm(audio)
        duration_ms = int(
            (len(pcm) / float(SAMPLE_RATE)) * 1000
        ) if pcm is not None else int(
            (transcribed or {}).get("transcribed_duration_ms") or 0
        )
        if duration_ms < 1:
            raise ValueError("audio duration could not be verified")
        conditions_raw = request.form.get("recording_conditions")
        conditions = json.loads(conditions_raw) if conditions_raw else {}
        if not isinstance(conditions, dict):
            raise TypeError("recording_conditions must be an object")
        conditions = {
            **conditions,
            "content_type": content_type,
            "client_version": request.form.get("client_version"),
        }
        attempt = db.attach_exercise_practice_service_attempt({
            "p_recovery_id": stored.recovery_id,
            "p_processing_recording_attempt_id": recording_attempt_id,
            "p_processing_audio_object_id": audio_object_id,
            "p_practice_acquisition_receipt_id": finalized[
                "practice_acquisition_receipt_id"
            ],
            "p_transcription_run_id": str(transcription_run["id"]),
            "p_exact_passage": str(session["exact_passage"]),
            "p_duration_ms": duration_ms,
            "p_capture_started_at": capture_started_at,
            "p_capture_completed_at": capture_completed_at,
            "p_recording_conditions": conditions,
            "p_idempotency_key": f"{idempotency}:attempt",
        })
        if attempt is None:
            return _service_unavailable()
        raw_measurements, safeguards, reasons = (
            extract_rushed_phrase_endings_n1(
                exact_passage=str(session["exact_passage"]),
                transcript=transcript,
                words=words,
                pcm=pcm,
                language=(transcribed or {}).get("language"),
            )
        )
        measurement = db.record_exercise_practice_service_measurement({
            "p_attempt_id": str(attempt["id"]),
            "p_measurement_revision": 1,
            "p_extractor_version": EXTRACTOR_VERSION,
            "p_feature_schema_version": FEATURE_SCHEMA_VERSION,
            "p_raw_measurements": raw_measurements,
            "p_safeguards": safeguards,
            "p_idempotency_key": f"{idempotency}:measurement",
        })
        if measurement is None:
            return _service_unavailable()
        validity = db.record_exercise_practice_service_validity({
            "p_attempt_id": str(attempt["id"]),
            "p_measurement_revision_id": str(measurement["id"]),
            "p_baseline_revision": int(session["baseline_revision"]),
            "p_validity": "valid" if not reasons else "invalid",
            "p_reason_codes": reasons,
            "p_validity_contract_version": VALIDITY_CONTRACT_VERSION,
            "p_idempotency_key": f"{idempotency}:validity",
        })
        if validity is None:
            return _service_unavailable()
        selection = db.freeze_exercise_practice_service_selection({
            "p_session_id": str(session["id"]),
            "p_acquisition_principal_id": principal,
            "p_baseline_revision": int(session["baseline_revision"]),
            "p_revision": attempt_index,
            "p_idempotency_key": f"{idempotency}:selection",
        })
        if selection is None:
            return _service_unavailable()
        processed_event = db.record_exercise_practice_service_event({
            "p_session_id": str(session["id"]),
            "p_acquisition_principal_id": principal,
            "p_recipient_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_attempt_id": str(attempt["id"]),
            "p_event_kind": "attempt_processed",
            "p_render_instance_id": render_instance,
            "p_content_identity_sha256": content_hash,
            "p_event_payload": {
                "validity": validity["validity"],
                "selection_state": selection["selection_state"],
            },
            # Keep the terminal product event replayable after a lost HTTP
            # response; this timestamp is part of its immutable event hash.
            "p_occurred_at": capture_completed_at,
            "p_idempotency_key": f"{idempotency}:attempt_processed",
        })
        if processed_event is None:
            return _service_unavailable()
        media_read = db.resolve_exercise_practice_media_read(
            str(attempt["id"]), principal,
        )
        if not media_read:
            return _service_unavailable()
        from services.user_media_storage import presigned_get_user_media_r2

        playback_url = presigned_get_user_media_r2(
            str(media_read["object_key"]), expires_in=900,
            bucket=str(media_read["bucket"]),
        )
        owner_pair = None
        if (
            selection.get("selection_state") == "selected_first_valid"
            and str(selection.get("selected_attempt_id") or "")
            == str(attempt["id"])
        ):
            pair = db.freeze_exercise_service_pair({
                "p_practice_session_id": str(session["id"]),
                "p_acquisition_principal_id": principal,
                "p_selection_revision_id": str(selection["id"]),
                "p_comparison_revision": int(selection["revision"]),
                "p_idempotency_key": f"{idempotency}:pair",
            })
            if pair is None:
                return _service_unavailable()
            assignment = db.assign_exercise_service_owner_pair({
                "p_pair_revision_id": str(pair["id"]),
                "p_acquisition_principal_id": principal,
                "p_idempotency_key": f"{idempotency}:owner-pair",
            })
            if assignment is None:
                return _service_unavailable()
            owner_pair = {
                "pair_revision_id": str(pair["id"]),
                "pair_assignment_id": str(assignment["id"]),
                "left_clip": assignment["left_clip"],
                "right_clip": assignment["right_clip"],
                "answer_taxonomy_version": (
                    "paired-listening-preference-five-state-v1"
                ),
            }
        return jsonify({
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
            "serves_user": False,
            "dataset_eligible": False,
        }), 201
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return _error(ValueError(str(error)))


@v2_bp.post("/user/mlc3/practice-sessions/<session_id>/preference")
@require_auth
@mlc3_pilot_required
def v2_mlc3_practice_preference(session_id: str):
    try:
        body = _body()
        principal = _principal_id()
        session = db.get_exercise_practice_service_session(
            _uuid(session_id, "session_id"), principal
        )
        if session is None:
            return jsonify({"code": "NOT_FOUND"}), 404
        answer = str(body.get("answer") or "")
        if answer not in {
            "prefer_left", "prefer_right", "same", "not_sure",
            "audio_unusable",
        }:
            raise ValueError("answer is not a paired preference value")
        row = db.submit_exercise_service_owner_pair_judgment({
            "p_pair_assignment_id": _uuid(
                body.get("pair_assignment_id"), "pair_assignment_id"
            ),
            "p_acquisition_principal_id": principal,
            "p_answer": answer,
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({
            "judgment_id": str(row["id"]),
            "answer": row["answer"],
            "meaning": "subjective_listening_preference_only",
            "serves_user": False,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.get("/user/mlc3/guidance/<membership_id>")
@require_auth
@mlc3_pilot_required
def v2_mlc3_user_guidance(membership_id: str):
    """Deliver assigned guidance; delivery remains separate from exposure."""
    try:
        principal = _principal_id()
        membership = _uuid(membership_id, "membership_id")
        base_key = _idempotency_key()
        rows = db.list_coach_guidance_service_assignments(
            membership, principal,
        )
        if rows is None:
            return _service_unavailable()
        payload = []
        for item in rows:
            attachment = item["attachment"]
            version = item["version"]
            delivered = db.record_coach_guidance_service_event({
                "p_attachment_version_id": str(version["id"]),
                "p_recipient_principal_id": principal,
                "p_event_kind": "delivered",
                "p_render_instance_id": None,
                "p_event_payload": {
                    "membership_id": membership,
                    "version_sha256": version["version_sha256"],
                },
                "p_idempotency_key": f"{base_key}:{version['id']}:delivered",
            })
            if not delivered:
                return _service_unavailable()
            media_url = None
            media_content_type = None
            if version.get("media_binding_id"):
                media = db.resolve_coach_guidance_service_media_read(
                    str(version["id"]), principal,
                )
                if not media:
                    return _service_unavailable()
                media_url = presigned_get_coach_object_r2(
                    str(media["bucket"]), str(media["object_key"]),
                    expires_in=900,
                )
                if not media_url:
                    return _service_unavailable()
                media_content_type = media["content_type"]
            payload.append({
                "attachment_version_id": str(version["id"]),
                "feedback_candidate_id": str(
                    attachment["feedback_candidate_id"]
                ),
                "attachment_class": attachment["attachment_class"],
                "written_note": version.get("written_note"),
                "media_url": media_url,
                "media_content_type": media_content_type,
                "version_sha256": version["version_sha256"],
                "serves_user": True,
                "dataset_eligible": False,
            })
        return jsonify({
            "membership_id": membership,
            "attachments": payload,
            "dataset_eligible": False,
        }), 200
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/guidance/<attachment_version_id>/events")
@require_auth
@mlc3_pilot_required
def v2_mlc3_user_guidance_event(attachment_version_id: str):
    try:
        body = _body()
        event_kind = str(body.get("event_kind") or "")
        if event_kind not in {"rendered", "played"}:
            raise ValueError("event_kind must be rendered or played")
        render_instance_id = (
            _uuid(body.get("render_instance_id"), "render_instance_id")
            if event_kind == "rendered" else None
        )
        row = db.record_coach_guidance_service_event({
            "p_attachment_version_id": _uuid(
                attachment_version_id, "attachment_version_id"
            ),
            "p_recipient_principal_id": _principal_id(),
            "p_event_kind": event_kind,
            "p_render_instance_id": render_instance_id,
            "p_event_payload": _event_payload(body.get("event_payload")),
            "p_idempotency_key": _idempotency_key(),
        })
        if not row:
            return _service_unavailable()
        return jsonify({
            "event_id": str(row["id"]),
            "event_kind": event_kind,
        }), 201
    except (TypeError, ValueError) as error:
        return _error(error)
