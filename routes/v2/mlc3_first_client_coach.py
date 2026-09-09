"""Coach-side blind review for the allowlisted first-client exercise loop."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from flask import Response, jsonify, request

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.blind_review_media import load_authorized_blind_clip
from services.coach_guidance_delivery import (
    inline_authoring_is_enabled,
    runtime_is_enabled,
)
from services.db import db as identity_db
from services.db import first_client_repository as db
from services.user_media_storage import get_user_media_r2_bytes

_DECISIONS = {
    "rating_yes", "rating_in_between", "rating_no",
    "rating_not_sure", "rating_audio_unclear",
}


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field} must be a UUID") from error


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


def _reviewer_principal_id() -> str:
    user_id = _uuid(getattr(request, "user_id", None), "reviewer_user_id")
    principal = identity_db.get_owner_principal_for_user(user_id) or {}
    return _uuid(principal.get("id"), "reviewer_principal_id")


def _closed():
    return jsonify({"code": "NOT_FOUND"}), 404


def _unavailable():
    return jsonify({"code": "MLC3_COACH_REVIEW_NOT_AVAILABLE"}), 409


def _assignment_payload(
    row: dict, judgment: dict | None, _reviewer_principal_id: str,
) -> dict | None:
    playback_reference_id = str(row.get("playback_reference_id") or "")
    try:
        playback_reference_id = _uuid(
            playback_reference_id, "playback_reference_id"
        )
    except ValueError:
        return None
    return {
        "assignment_id": str(row["id"]),
        "audio_ref": (
            "/api/v2/coach/mlc3/reviews/playback/" + playback_reference_id
        ),
        "packet_sha256": row["packet_sha256"],
        "taxonomy_version": row["taxonomy_version"],
        "judgment": judgment["decision"] if judgment else None,
        # Transcript and measurements are deliberately absent before reveal.
        "serves_user": False,
        "dataset_eligible": False,
    }


@v2_bp.get("/coach/mlc3/reviews/playback/<playback_reference_id>")
@require_admin_or_coach
def v2_coach_mlc3_blind_playback(playback_reference_id: str):
    if not runtime_is_enabled():
        return _closed()
    try:
        reviewer = _reviewer_principal_id()
        opaque_reference = _uuid(
            playback_reference_id, "playback_reference_id"
        )
        clip = load_authorized_blind_clip(
            resolve=lambda: db.resolve_exercise_confidence_media_read(
                opaque_reference, reviewer,
            ),
            load=lambda object_row: get_user_media_r2_bytes(
                str(object_row["object_key"]),
                bucket=str(object_row["bucket"]),
            ),
        )
        response = Response(clip, status=200, mimetype="audio/wav")
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    except Exception:
        return _unavailable()


@v2_bp.get("/coach/mlc3/source-playback/<assignment_id>")
@require_admin_or_coach
def v2_coach_mlc3_source_playback(assignment_id: str):
    """Return only the exact canonical source clip for one blind assignment."""
    if not inline_authoring_is_enabled():
        return _closed()
    try:
        reviewer_user = _uuid(
            getattr(request, "user_id", None), "reviewer_user_id"
        )
        reviewer = _reviewer_principal_id()
        opaque_assignment = _uuid(assignment_id, "assignment_id")
        clip = load_authorized_blind_clip(
            resolve=lambda: db.resolve_coach_inline_blind_audio_read(
                opaque_assignment, reviewer_user, reviewer,
            ),
            load=lambda object_row: get_user_media_r2_bytes(
                str(object_row["object_key"]),
                bucket=str(object_row["bucket"]),
            ),
        )
        response = Response(clip, status=200, mimetype="audio/wav")
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    except Exception:
        return _unavailable()


def _project_acquisition_principal(project_id: str) -> str:
    identity = db.get_project_identity(project_id) or {}
    return _uuid(
        identity.get("owner_principal_id"), "acquisition_principal_id"
    )


@v2_bp.post("/coach/mlc3/inline/assignments/<assignment_id>/render")
@require_admin_or_coach
def v2_coach_mlc3_inline_render(assignment_id: str):
    if not inline_authoring_is_enabled():
        return _closed()
    try:
        body = _body()
        project_id = _uuid(body.get("project_id"), "project_id")
        row = db.ack_coach_inline_blind_render({
            "p_review_assignment_id": _uuid(
                assignment_id, "review_assignment_id"
            ),
            "p_blind_packet_id": _uuid(
                body.get("blind_packet_id"), "blind_packet_id"
            ),
            "p_presentation_id": _uuid(
                body.get("presentation_id"), "presentation_id"
            ),
            "p_acknowledgement_token": _uuid(
                body.get("acknowledgement_token"), "acknowledgement_token"
            ),
            "p_acquisition_principal_id": _project_acquisition_principal(
                project_id
            ),
            "p_reviewer_principal_id": _reviewer_principal_id(),
            "p_render_instance_id": _uuid(
                body.get("render_instance_id"), "render_instance_id"
            ),
            "p_client_rendered_at": str(
                body.get("client_rendered_at") or ""
            ),
            "p_client_version": str(body.get("client_version") or ""),
            "p_visible_payload_sha256": str(
                body.get("visible_payload_sha256") or ""
            ),
            "p_idempotency_key": _idempotency_key(),
        })
        if not row:
            return _unavailable()
        return jsonify({"exposure_id": str(row["id"])}), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.post("/coach/mlc3/inline/assignments/<assignment_id>/judgments")
@require_admin_or_coach
def v2_coach_mlc3_inline_judgment(assignment_id: str):
    if not inline_authoring_is_enabled():
        return _closed()
    try:
        body = _body()
        decision = str(body.get("decision") or "")
        if decision not in _DECISIONS:
            raise ValueError("decision is not in the five-state taxonomy")
        project_id = _uuid(body.get("project_id"), "project_id")
        row = db.submit_coach_inline_blind_judgment({
            "p_review_assignment_id": _uuid(
                assignment_id, "review_assignment_id"
            ),
            "p_blind_packet_id": _uuid(
                body.get("blind_packet_id"), "blind_packet_id"
            ),
            "p_acquisition_principal_id": _project_acquisition_principal(
                project_id
            ),
            "p_reviewer_principal_id": _reviewer_principal_id(),
            "p_exposure_id": _uuid(body.get("exposure_id"), "exposure_id"),
            "p_decision": decision,
            "p_decided_at": datetime.now(UTC).isoformat(),
            "p_idempotency_key": _idempotency_key(),
        })
        if not row:
            return _unavailable()
        return jsonify({
            "judgment_id": str(row["judgment_id"]),
            "decision": str(row["decision"]),
            "meaning": "blind_confidence_judgment_only",
            "serves_user": False,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.get("/coach/mlc3/reviews/<project_id>")
@require_admin_or_coach
def v2_coach_mlc3_reviews(project_id: str):
    if not runtime_is_enabled():
        return _closed()
    try:
        project = _uuid(project_id, "project_id")
        reviewer = _reviewer_principal_id()
        result = []
        sessions = db.list_exercise_service_review_sessions(project)
        if sessions is None:
            return _unavailable()
        for session in sessions:
            review_set = db.freeze_exercise_service_blind_review_set({
                "p_practice_session_id": str(session["id"]),
                "p_reviewer_principal_id": reviewer,
                "p_idempotency_key": (
                    f"first-client-review:{session['id']}:{reviewer}"
                ),
            })
            if not review_set:
                return _unavailable()
            state = db.get_exercise_service_blind_review_set(
                str(review_set["id"]), reviewer,
            )
            if not state:
                return _unavailable()
            judgments = {
                str(item["assignment_id"]): item
                for item in state.get("judgments") or []
            }
            assignments = []
            for assignment in state.get("assignments") or []:
                public = _assignment_payload(
                    assignment, judgments.get(str(assignment["id"])), reviewer,
                )
                if public is None:
                    return _unavailable()
                assignments.append(public)
            # Freeze a stable opaque order without exposing which assignment
            # is the original or the practice clip before judgment.
            assignments.sort(key=lambda item: sha256(
                (
                    f"{state['id']}:{item['assignment_id']}:"
                    "confidence-blind-order-v1"
                ).encode("utf-8")
            ).hexdigest())
            result.append({
                "review_set_id": str(state["id"]),
                "practice_session_id": str(state["practice_session_id"]),
                "assignments": assignments,
                "complete": bool(assignments) and all(
                    item["judgment"] is not None for item in assignments
                ),
                "serves_user": False,
                "dataset_eligible": False,
            })
        return jsonify({
            "project_id": project,
            "review_sets": result,
            "serves_user": False,
            "dataset_eligible": False,
        }), 200
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.post("/coach/mlc3/reviews/assignments/<assignment_id>/render")
@require_admin_or_coach
def v2_coach_mlc3_review_render(assignment_id: str):
    if not runtime_is_enabled():
        return _closed()
    try:
        body = _body()
        row = db.ack_exercise_service_confidence_render({
            "p_assignment_id": _uuid(assignment_id, "assignment_id"),
            "p_reviewer_principal_id": _reviewer_principal_id(),
            "p_render_instance_id": _uuid(
                body.get("render_instance_id"), "render_instance_id"
            ),
            "p_packet_sha256": str(body.get("packet_sha256") or ""),
            "p_rendered_at": str(body.get("rendered_at") or ""),
            "p_client_version": str(body.get("client_version") or ""),
            "p_idempotency_key": _idempotency_key(),
        })
        if not row:
            return _unavailable()
        return jsonify({"render_receipt_id": str(row["id"])}), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.post("/coach/mlc3/reviews/assignments/<assignment_id>/judgments")
@require_admin_or_coach
def v2_coach_mlc3_review_judgment(assignment_id: str):
    if not runtime_is_enabled():
        return _closed()
    try:
        body = _body()
        decision = str(body.get("decision") or "")
        if decision not in _DECISIONS:
            raise ValueError("decision is not in the five-state taxonomy")
        row = db.submit_exercise_service_confidence_judgment({
            "p_assignment_id": _uuid(assignment_id, "assignment_id"),
            "p_reviewer_principal_id": _reviewer_principal_id(),
            "p_render_receipt_id": _uuid(
                body.get("render_receipt_id"), "render_receipt_id"
            ),
            "p_decision": decision,
            "p_decided_at": datetime.now(UTC).isoformat(),
            "p_idempotency_key": _idempotency_key(),
        })
        if not row:
            return _unavailable()
        return jsonify({
            "judgment_id": str(row["id"]),
            "decision": row["decision"],
            "meaning": "blind_confidence_judgment_only",
            "serves_user": False,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.post("/coach/mlc3/reviews/<review_set_id>/complete")
@require_admin_or_coach
def v2_coach_mlc3_review_complete(review_set_id: str):
    if not runtime_is_enabled():
        return _closed()
    try:
        row = db.complete_exercise_service_blind_review({
            "p_review_set_id": _uuid(review_set_id, "review_set_id"),
            "p_reviewer_principal_id": _reviewer_principal_id(),
            "p_idempotency_key": _idempotency_key(),
        })
        if not row:
            return _unavailable()
        return jsonify({
            "reveal_grant_id": str(row["id"]),
            "serves_user": False,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
