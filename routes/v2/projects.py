"""Canonical Project lifecycle and guest-owner claim routes."""
from __future__ import annotations

import logging
import uuid

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth, require_auth
from routes.admin import require_admin
from routes.v2.blueprint import v2_bp
from services.db import db
from services.project_ownership import (
    GUEST_OWNER_HEADER,
    issue_guest_owner,
    parse_guest_owner_token,
    verify_guest_owner,
)
from services.project_repository import ProjectOwnershipError, ProjectRepository
from services.project_deletion import (
    ProjectDeletionError,
    ProjectDeletionService,
    public_view,
)
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
        if result.get("reason") == "processing_authorization_required":
            return jsonify({
                "code": result.get("code") or "PROCESSING_AUTHORIZATION_REQUIRED",
                "error": "Current processing authorization is required before coach review.",
                "project_id": project_id,
                "take_id": take_id,
            }), 403
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


def _deletion_owner(project_id: str):
    """The signed-in owner principal, or a (response, status) to return."""
    if not _is_valid_uuid(project_id):
        return None, (jsonify({"code": "INVALID_INPUT",
                               "error": "project_id must be a UUID"}), 400)
    repository = ProjectRepository(db)
    try:
        principal = repository.owner_for_user(str(getattr(request, "user_id", "")))
    except ProjectOwnershipError:
        return None, (jsonify({"code": "PROJECT_NOT_FOUND",
                               "error": "Project not found"}), 404)
    return principal, None


def _deletion_error(error: ProjectDeletionError):
    return jsonify({"code": error.code, "error": error.message}), error.status


@v2_bp.route("/projects/<project_id>/deletion-request", methods=["POST"])
@require_auth
def v2_request_project_deletion(project_id: str):
    """Ask for one owned project to be deleted (P1-A, decisions log N8).

    A request, not a delete: an operator confirms it within 7 days and the
    project is locked until then. Idempotent on `idempotency_key`; asking again
    for a project with an open request returns that request.
    201 {deletion} · 400 · 404 not the owner's project · 503 not migrated.
    """
    principal, failure = _deletion_owner(project_id)
    if failure:
        return failure
    body = request.get_json(silent=True) or {}
    key = str(body.get("idempotency_key") or "").strip()
    if not key or len(key) > 200:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "idempotency_key is required"}), 400
    try:
        row = ProjectDeletionService(db).request(principal.id, project_id, key)
    except ProjectDeletionError as error:
        return _deletion_error(error)
    except Exception as error:
        logger.error("project deletion request failed project=%s: %s",
                     project_id, error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not request deletion"}), 500
    logger.info("project deletion requested project=%s request=%s state=%s",
                project_id, row.get("id"), row.get("state"))
    return jsonify({"deletion": public_view(row)}), 201


@v2_bp.route("/projects/<project_id>/deletion-request", methods=["DELETE"])
@require_auth
def v2_cancel_project_deletion(project_id: str):
    """Cancel a pending deletion before an operator confirms it.
    200 {deletion} · 409 nothing pending, or already confirmed."""
    principal, failure = _deletion_owner(project_id)
    if failure:
        return failure
    try:
        row = ProjectDeletionService(db).cancel(principal.id, project_id)
    except ProjectDeletionError as error:
        return _deletion_error(error)
    except Exception as error:
        logger.error("project deletion cancel failed project=%s: %s",
                     project_id, error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not cancel deletion"}), 500
    logger.info("project deletion cancelled project=%s request=%s",
                project_id, row.get("id"))
    return jsonify({"deletion": public_view(row)}), 200


@v2_bp.route("/admin/project-deletions/<request_id>/confirm", methods=["POST"])
@require_admin
def v2_admin_confirm_project_deletion(request_id: str):
    """The operator confirms one project deletion (P1-B, N8). Creates the
    one-project purge request; the owner can no longer cancel. Nothing is
    deleted here: the purge runs only when an operator runs
    scripts/run_phase1_data_purge.py with PHASE1_PURGE_EXECUTION_ENABLED and
    the request id repeated. Idempotent. Admin-only surface.
    200 {deletion, purge_request_id} · 400 · 404 · 409 no longer pending."""
    if not _is_valid_uuid(request_id):
        return jsonify({"code": "INVALID_INPUT", "error": "Invalid request id"}), 400
    operator = str(getattr(request, "user_id", "") or "")
    if not _is_valid_uuid(operator):
        return jsonify({"code": "INVALID_INPUT", "error": "Invalid operator"}), 400
    try:
        row = ProjectDeletionService(db).confirm(request_id, operator)
    except ProjectDeletionError as error:
        return _deletion_error(error)
    except Exception as error:
        logger.error("project deletion confirm failed request=%s: %s",
                     request_id, error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not confirm deletion"}), 500
    logger.info("project deletion confirmed request=%s purge=%s operator=%s",
                request_id, row.get("purge_request_id"), operator)
    return jsonify({"deletion": public_view(row),
                    "purge_request_id": str(row.get("purge_request_id") or "")}), 200


@v2_bp.route("/admin/project-deletions", methods=["GET"])
@require_admin
def v2_admin_project_deletions():
    """Operator queue (P1-A, N8): open project deletion requests, oldest due
    first; POST .../<request_id>/confirm confirms one (P1-B).
    Admin-only surface."""
    try:
        rows = ProjectDeletionService(db).queue()
        ids = [str(r["project_id"]) for r in rows if r.get("project_id")]
        names: dict[str, str] = {}
        if ids:
            projects = (db.client.table("projects")
                        .select("id,display_name").in_("id", ids)
                        .execute().data or [])
            names = {str(p["id"]): str(p.get("display_name") or "")
                     for p in projects}
    except Exception as error:
        logger.error("admin project deletions failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not load project deletions"}), 500
    return jsonify({"requests": [
        {**(public_view(r) or {}),
         "acquisition_principal_id": str(r.get("acquisition_principal_id")),
         "confirmed_at": r.get("confirmed_at"),
         "project_name": names.get(str(r.get("project_id")), "")}
        for r in rows
    ]}), 200
