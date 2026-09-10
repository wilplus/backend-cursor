"""Rollout-aware MLC-3 exercise service loop.

Every endpoint is hidden behind authentication, the backend master switch,
the exact acquisition-principal enrollment, and the database service contract.
Dataset, training, evaluation, and promotion operations do not exist here.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from flask import Response, jsonify, request

from auth import require_auth
from config import Config
from routes.phase2_guard import mlc3_service_required
from routes.v2.blueprint import v2_bp
from services.coach_guidance_delivery import require_audio_upload
from services.coach_video_storage import get_coach_object_r2_bytes
from services.db import first_client_repository as db
from services.practice_attempt_orchestrator import (
    PracticeAttemptCommand,
    PracticeAttemptNotFound,
    PracticeAttemptOrchestrator,
    PracticeAttemptUnavailable,
)
from services.user_media_storage import get_user_media_r2_bytes

practice_attempt_orchestrator = PracticeAttemptOrchestrator(db)
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


def _speaker_result(row: dict) -> dict:
    return {
        "assertion_id": str(row["assertion_id"]),
        "speaker_id": str(row["speaker_id"]),
        "target_binding_id": str(row["target_binding_id"]),
        "replayed": bool(row.get("replayed")),
        "meaning": "identity_routing_only",
        "dataset_eligible": False,
    }


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
        payload["exercise"] = {
            "version_id": str(version["id"]),
            "instruction_text": version["instruction_text"],
            "content_identity_sha256": version["version_sha256"],
            "media_url": (
                f"/api/v2/user/mlc3/exercise-offers/{offer['id']}/playback"
            ),
            "media_content_type": media.get("content_type"),
        }
    return payload


def _private_media_response(
    body: bytes, *, content_type: str,
) -> Response:
    response = Response(body, status=200, mimetype=content_type)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _exact_media_matches(before: dict, after: dict) -> bool:
    return all(
        str(before.get(key)) == str(after.get(key))
        for key in (
            "bucket", "object_key", "exact_bytes_sha256", "byte_size",
            "content_type",
        )
    )


@v2_bp.post("/user/mlc3/feedback/render")
@require_auth
@mlc3_service_required
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
@mlc3_service_required
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


@v2_bp.post("/user/mlc3/feedback/speaker")
@require_auth
@mlc3_service_required
def v2_mlc3_feedback_self_speaker():
    """Record only an explicit affirmative source-voice confirmation."""
    try:
        body = _body()
        if body.get("assertion") != "this_is_my_voice":
            raise ValueError(
                "only an affirmative self-speaker action is accepted"
            )
        row = db.record_feedback_self_speaker_target({
            "p_acquisition_principal_id": _principal_id(),
            "p_owner_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_membership_id": _uuid(
                body.get("membership_id"), "membership_id"
            ),
            "p_candidate_id": _uuid(body.get("candidate_id"), "candidate_id"),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify(_speaker_result(row)), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.post("/user/mlc3/exercise-offers")
@require_auth
@mlc3_service_required
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
@mlc3_service_required
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


@v2_bp.get("/user/mlc3/exercise-offers/<offer_id>/playback")
@require_auth
@mlc3_service_required
def v2_mlc3_exercise_offer_playback(offer_id: str):
    """Serve exact exercise bytes through the authenticated application."""
    try:
        principal = _principal_id()
        exact_offer_id = _uuid(offer_id, "offer_id")
        before = db.resolve_exercise_service_offer_read(
            exact_offer_id, principal,
        )
        media = (before or {}).get("media")
        if not isinstance(media, dict):
            return _service_unavailable()
        body = get_coach_object_r2_bytes(
            str(media["bucket"]), str(media["object_key"])
        )
        if (
            len(body) != int(media["byte_size"])
            or sha256(body).hexdigest() != str(media["exact_bytes_sha256"])
        ):
            return _service_unavailable()
        after = db.resolve_exercise_service_offer_read(
            exact_offer_id, principal,
        )
        after_media = (after or {}).get("media")
        if not isinstance(after_media, dict) or not _exact_media_matches(
            media, after_media,
        ):
            return _service_unavailable()
        return _private_media_response(
            body, content_type=str(media["content_type"])
        )
    except (TypeError, ValueError, KeyError, RuntimeError):
        return _service_unavailable()


@v2_bp.post("/user/mlc3/exercise-offers/<offer_id>/events")
@require_auth
@mlc3_service_required
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
@mlc3_service_required
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
@mlc3_service_required
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
@mlc3_service_required
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


@v2_bp.post("/user/mlc3/practice-sessions/<session_id>/attempts")
@require_auth
@mlc3_service_required
def v2_mlc3_practice_attempt(session_id: str):
    try:
        upload = request.files.get("audio")
        if upload is None:
            raise ValueError("audio is required")
        audio = upload.read(Config.MLC3_PILOT_MAX_AUDIO_MB * 1024 * 1024 + 1)
        content_type = require_audio_upload(
            body=audio,
            content_type=upload.mimetype or "",
            max_bytes=Config.MLC3_PILOT_MAX_AUDIO_MB * 1024 * 1024,
        )
        conditions_raw = request.form.get("recording_conditions")
        conditions = json.loads(conditions_raw) if conditions_raw else {}
        if not isinstance(conditions, dict):
            raise TypeError("recording_conditions must be an object")
        command = PracticeAttemptCommand(
            session_id=_uuid(session_id, "session_id"),
            principal_id=_principal_id(),
            owner_user_id=_uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            idempotency_key=_idempotency_key(),
            render_instance_id=_uuid(
                request.form.get("render_instance_id"), "render_instance_id"
            ),
            content_identity_sha256=_sha256(
                request.form.get("content_identity_sha256"),
                "content_identity_sha256",
            ),
            capture_started_at=_rpc_time(
                request.form.get("capture_started_at"), "capture_started_at"
            ),
            capture_completed_at=_rpc_time(
                request.form.get("capture_completed_at"), "capture_completed_at"
            ),
            audio=audio,
            # Preserve the raw filename for immutable object-key replay.
            # The orchestrator applies a transcription-only hint when absent.
            filename=upload.filename or "",
            content_type=content_type,
            recording_conditions=conditions,
            client_version=request.form.get("client_version"),
        )
        return jsonify(practice_attempt_orchestrator.execute(command)), 201
    except PracticeAttemptNotFound:
        return jsonify({"code": "NOT_FOUND"}), 404
    except PracticeAttemptUnavailable:
        return _service_unavailable()
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        return _error(ValueError(str(error)))


@v2_bp.get("/user/mlc3/practice-attempts/<attempt_id>/playback")
@require_auth
@mlc3_service_required
def v2_mlc3_practice_attempt_playback(attempt_id: str):
    """Serve exact practice bytes with live checks on both sides of R2."""
    try:
        principal = _principal_id()
        exact_attempt_id = _uuid(attempt_id, "attempt_id")
        before = db.resolve_exercise_practice_media_read(
            exact_attempt_id, principal,
        )
        if not isinstance(before, dict):
            return _service_unavailable()
        body = get_user_media_r2_bytes(
            str(before["object_key"]), bucket=str(before["bucket"])
        )
        if (
            len(body) != int(before["byte_size"])
            or sha256(body).hexdigest() != str(before["exact_bytes_sha256"])
        ):
            return _service_unavailable()
        after = db.resolve_exercise_practice_media_read(
            exact_attempt_id, principal,
        )
        if not isinstance(after, dict) or not _exact_media_matches(before, after):
            return _service_unavailable()
        return _private_media_response(
            body, content_type=str(before["content_type"])
        )
    except (TypeError, ValueError, KeyError, RuntimeError):
        return _service_unavailable()



@v2_bp.post("/user/mlc3/practice-sessions/<session_id>/preference")
@require_auth
@mlc3_service_required
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


@v2_bp.post("/user/mlc3/practice-attempts/<attempt_id>/speaker")
@require_auth
@mlc3_service_required
def v2_mlc3_practice_self_speaker(attempt_id: str):
    """Confirm the practice voice and create a pair only for the same speaker."""
    try:
        body = _body()
        if body.get("assertion") != "this_is_my_voice":
            raise ValueError(
                "only an affirmative self-speaker action is accepted"
            )
        row = db.confirm_practice_speaker_and_pair({
            "p_acquisition_principal_id": _principal_id(),
            "p_owner_user_id": _uuid(
                getattr(request, "user_id", None), "owner_user_id"
            ),
            "p_practice_attempt_id": _uuid(attempt_id, "attempt_id"),
            "p_idempotency_key": _idempotency_key(),
        })
        if row is None:
            return _service_unavailable()
        return jsonify({
            "speaker_target": _speaker_result(row["speaker_target"]),
            "eligibility_result": row["eligibility_result"],
            "owner_pair": row.get("owner_pair"),
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError) as error:
        return _error(error)


@v2_bp.get("/user/mlc3/guidance/<membership_id>")
@require_auth
@mlc3_service_required
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
                media_url = (
                    f"/api/v2/user/mlc3/guidance/{version['id']}/playback"
                )
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


@v2_bp.get("/user/mlc3/guidance/<attachment_version_id>/playback")
@require_auth
@mlc3_service_required
def v2_mlc3_user_guidance_playback(attachment_version_id: str):
    """Serve assigned private guidance with before/after authority checks."""
    try:
        principal = _principal_id()
        version_id = _uuid(attachment_version_id, "attachment_version_id")
        before = db.resolve_coach_guidance_service_media_read(
            version_id, principal,
        )
        if not isinstance(before, dict):
            return _service_unavailable()
        body = get_coach_object_r2_bytes(
            str(before["bucket"]), str(before["object_key"])
        )
        if (
            len(body) != int(before["byte_size"])
            or sha256(body).hexdigest() != str(before["exact_bytes_sha256"])
        ):
            return _service_unavailable()
        after = db.resolve_coach_guidance_service_media_read(
            version_id, principal,
        )
        if not isinstance(after, dict) or not _exact_media_matches(before, after):
            return _service_unavailable()
        return _private_media_response(
            body, content_type=str(before["content_type"])
        )
    except (TypeError, ValueError, KeyError, RuntimeError):
        return _service_unavailable()


@v2_bp.post("/user/mlc3/guidance/<attachment_version_id>/events")
@require_auth
@mlc3_service_required
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
