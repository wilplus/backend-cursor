"""Canonical Project lifecycle and guest-owner claim routes."""
from __future__ import annotations

import logging
import uuid

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth, require_auth
from routes.v2.blueprint import v2_bp
from services.db import db
from services.project_ownership import (
    GUEST_OWNER_HEADER,
    issue_guest_owner,
    parse_guest_owner_token,
    verify_guest_owner,
)
from services.project_repository import ProjectOwnershipError, ProjectRepository
from services.lab_send import send_lab_recording_to_coach
from routes.v2.common import _is_valid_uuid


logger = logging.getLogger(__name__)


_POST_SIGNUP_CONFIRMATION = {
    "headline": "We're on it.",
    "body": (
        "A human reviews every recording personally — your full "
        "analysis lands within one business day."
    ),
}


def _request_guest_token() -> str | None:
    return request.headers.get(GUEST_OWNER_HEADER)


def _existing_guest_principal(repository: ProjectRepository) -> str | None:
    token = _request_guest_token()
    parsed = parse_guest_owner_token(token)
    if not parsed:
        return None
    principal_id, _ = parsed
    return verify_guest_owner(token, repository.get_principal(principal_id))


@v2_bp.route("/projects", methods=["POST"])
@optional_auth
def v2_create_project():
    """Create the immutable Project before Take 1, signed in or as a guest."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "project must be a JSON object"}), 400
    display_name = str(body.get("display_name") or body.get("topic")
                       or "Presentation").strip()
    if not display_name or len(display_name) > 200:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "display_name must be 1–200 characters"}), 400
    setup = body.get("setup") if isinstance(body.get("setup"), dict) else {}
    presentation_ref = body.get("presentation_ref")
    if presentation_ref is not None and not isinstance(presentation_ref, str):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "presentation_ref must be a string"}), 400

    repository = ProjectRepository(db)
    guest_token = None
    try:
        user_id = getattr(request, "user_id", None)
        if user_id:
            principal = repository.owner_for_user(str(user_id))
        else:
            existing_id = _existing_guest_principal(repository)
            if existing_id:
                row = repository.get_principal(existing_id) or {}
                from services.canonical_product import OwnerPrincipal
                principal = OwnerPrincipal(str(row["id"]), None, True)
            else:
                issued = issue_guest_owner()
                principal = repository.create_guest_owner(
                    issued.principal_id, issued.secret_hash)
                guest_token = issued.token
        project = repository.create_project(
            project_id=str(uuid.uuid4()),
            owner_principal_id=principal.id,
            display_name=display_name,
            setup=setup,
            presentation_ref=presentation_ref,
        )
        payload = {
            "project_id": project.id,
            "display_name": project.display_name,
            "owner_principal_id": principal.id,
        }
        if guest_token:
            payload["guest_owner_token"] = guest_token
        return jsonify(payload), 201
    except ProjectOwnershipError as error:
        return jsonify({"code": "PROJECT_CREATE_FAILED",
                        "error": str(error)}), 500
    except Exception as error:
        logger.error("project create failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to create project"}), 500


@v2_bp.route("/projects/claim", methods=["POST"])
@require_auth
def v2_claim_guest_project_owner():
    """Atomically bind the complete guest-owned graph to this account."""
    repository = ProjectRepository(db)
    parsed = parse_guest_owner_token(_request_guest_token())
    if not parsed:
        return jsonify({"code": "INVALID_GUEST_OWNER",
                        "error": "A valid guest owner token is required"}), 400
    principal_id, supplied_hash = parsed
    principal = repository.get_principal(principal_id)
    if not verify_guest_owner(_request_guest_token(), principal):
        return jsonify({"code": "INVALID_GUEST_OWNER",
                        "error": "Guest owner token was rejected"}), 403
    try:
        claimed = repository.claim_guest(
            principal_id, supplied_hash, str(request.user_id))
        return jsonify({
            "owner_principal_id": str(claimed["id"]),
            "user_id": str(request.user_id),
            "claimed": True,
        }), 200
    except ProjectOwnershipError as error:
        return jsonify({"code": "GUEST_OWNER_CLAIM_FAILED",
                        "error": str(error)}), 409


@v2_bp.route(
    "/projects/<project_id>/takes/<take_id>/send-to-coach",
    methods=["POST"],
)
@require_auth
def v2_send_project_take_to_coach(project_id: str, take_id: str):
    """Send one exact, authenticated Project Take to asynchronous review."""
    if not _is_valid_uuid(project_id) or not _is_valid_uuid(take_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "project_id and take_id must be UUIDs"}), 400
    repository = ProjectRepository(db)
    try:
        user_id = str(getattr(request, "user_id", ""))
        principal = repository.owner_for_user(user_id)
        repository.require_owned_project(project_id, principal.id)
        repository.require_owned_take(project_id, take_id, principal.id)
    except ProjectOwnershipError:
        return jsonify({"code": "TAKE_NOT_FOUND",
                        "error": "Take not found"}), 404

    result = send_lab_recording_to_coach(take_id, user_id)
    if not result.get("ok"):
        return jsonify({
            "code": "SEND_FAILED",
            "error": "Your take is safe, but it could not be sent for review. Please retry.",
            "project_id": project_id,
            "take_id": take_id,
        }), 500

    try:
        from services.arc_notifications import backfill_ideal_bubbles

        backfill_ideal_bubbles(db, user_id, project_id)
    except Exception as error:
        logger.warning(
            "coach send: ideal bubble backfill failed project=%s take=%s: %s",
            project_id, take_id, error,
        )
    return jsonify({
        "status": "ok",
        "state": "review_pending",
        "project_id": project_id,
        "take_id": take_id,
        "review_pending": True,
        "already_sent": bool(result.get("already_sent")),
        "post_signup_confirmation": _POST_SIGNUP_CONFIRMATION,
    }), 200
