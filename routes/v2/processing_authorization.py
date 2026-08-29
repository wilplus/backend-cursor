"""Phase-1 processing agreement, AI transparency and data-rights routes."""
from __future__ import annotations

from functools import wraps
from flask import jsonify, request

from auth import optional_auth
from routes.v2.blueprint import v2_bp
from services.create_take import CreateTakeError, resolve_owner_principal
from services.db import db
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)
from services.project_ownership import GUEST_OWNER_HEADER
from services.project_ownership import (
    issue_guest_owner,
    parse_guest_owner_token,
    verify_guest_owner,
)
from services.project_repository import ProjectOwnershipError, ProjectRepository


_CORE_SERVICE_PREFIXES = (
    "/v2/lab/", "/v2/projects", "/v2/chat/", "/v2/coaching/",
    "/v2/explore/", "/v2/arc/", "/v2/voice-album",
    "/v2/user/sessions/", "/v2/user/snippets/",
)


def _principal_id() -> str:
    principal = resolve_owner_principal(
        ProjectRepository(db),
        user_id=getattr(request, "user_id", None),
        guest_token=request.headers.get(GUEST_OWNER_HEADER),
    )
    return ProcessingAuthorizationService(db).resolve_acquisition_principal(
        principal.id,
        user_id=str(getattr(request, "user_id", "") or "") or None,
    )


def _principal_error(error: Exception):
    status = error.status if isinstance(error, CreateTakeError) else 403
    code = error.code if isinstance(error, CreateTakeError) else "OWNER_REQUIRED"
    return jsonify({"code": code, "error": "A verified owner is required."}), status


def phase1_provider_route(function):
    """Bind a non-recording AI request to the caller's current authority.

    Recording work supplies exact Take coordinates in the worker. Lounge text
    has no Take/audio lineage, so its provider snapshot deliberately stores
    null source coordinates while retaining the acquisition principal.
    """
    @wraps(function)
    def wrapped(*args, **kwargs):
        service = ProcessingAuthorizationService(db)
        if not service.enforced:
            return function(*args, **kwargs)
        try:
            principal_id = _principal_id()
        except (CreateTakeError, ProjectOwnershipError) as error:
            return _principal_error(error)
        from services.authorized_provider import (
            AuthorizedProviderAdapter,
            ProviderCoordinates,
            protected_provider_scope,
        )
        import uuid

        try:
            service.require_current(principal_id, operation="ai_conversation")
        except ProcessingAuthorizationError as error:
            return jsonify({"code": error.code, "error": error.message}), error.status
        adapter = AuthorizedProviderAdapter(
            db,
            ProviderCoordinates(principal_id, None, None),
            authorization=service,
        )
        with protected_provider_scope(
            adapter,
            idempotency_prefix=f"ai-conversation:{uuid.uuid4()}",
        ):
            return function(*args, **kwargs)
    raw = function
    while getattr(raw, "__wrapped__", None) is not None:
        raw = raw.__wrapped__
    wrapped.__wrapped__ = raw
    return wrapped


@v2_bp.before_request
def enforce_phase1_processing_gate():
    """One route-independent core-service gate.

    The gate is inert until the explicit deployment mode is enabled. Once
    enabled, protected product routes cannot reproduce or bypass policy rules;
    they receive the database's typed decision from the central service.
    """
    if request.method == "OPTIONS":
        return None
    path = request.path
    if not any(path.startswith(prefix) for prefix in _CORE_SERVICE_PREFIXES):
        return None
    # Identity claim and authority/data-rights routes remain reachable. The
    # claim changes identity binding only and cannot create acceptance.
    if path == "/v2/projects/claim" or path.startswith(
        "/v2/processing-authorization"
    ):
        return None
    service = ProcessingAuthorizationService(db)
    if not service.enforced:
        return None
    try:
        principal_id = _principal_id()
        service.require_current(principal_id, operation="core_service")
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    return None


@v2_bp.route("/processing-authorization/principal", methods=["POST"])
@optional_auth
def v2_processing_principal():
    """Resolve an account principal or mint one signed guest principal.

    Minting identity is not acceptance. It writes no policy receipt and grants
    no processing authority; it merely gives a pre-signup user the durable
    acquisition identity required to make an explicit server-backed choice.
    """
    repository = ProjectRepository(db)
    user_id = getattr(request, "user_id", None)
    try:
        if user_id:
            principal = repository.owner_for_user(str(user_id))
            return jsonify({
                "owner_principal_id": principal.id,
                "is_guest": False,
            }), 200
        supplied = request.headers.get(GUEST_OWNER_HEADER)
        parsed = parse_guest_owner_token(supplied)
        if parsed:
            principal_id, _ = parsed
            if verify_guest_owner(supplied, repository.get_principal(principal_id)):
                return jsonify({
                    "owner_principal_id": principal_id,
                    "is_guest": True,
                }), 200
        issued = issue_guest_owner()
        principal = repository.create_guest_owner(
            issued.principal_id, issued.secret_hash
        )
        return jsonify({
            "owner_principal_id": principal.id,
            "is_guest": True,
            "guest_owner_token": issued.token,
        }), 201
    except ProjectOwnershipError:
        return jsonify({
            "code": "OWNER_CREATE_FAILED",
            "error": "The processing owner could not be established.",
        }), 503


@v2_bp.route("/processing-authorization", methods=["GET", "POST"])
@optional_auth
def v2_processing_authorization():
    try:
        principal_id = _principal_id()
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    service = ProcessingAuthorizationService(db)
    if request.method == "GET":
        return jsonify(service.status(principal_id)), 200
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"code": "INVALID_INPUT", "error": "JSON object required"}), 400
    try:
        return jsonify(service.accept(principal_id, payload)), 201
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status


@v2_bp.route("/processing-authorization/ai-rendered", methods=["POST"])
@optional_auth
def v2_processing_ai_rendered():
    try:
        principal_id = _principal_id()
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    payload = request.get_json(silent=True) or {}
    required = (
        "ai_notice_version", "surface", "client_render_id", "rendered_at",
        "client_version",
    )
    if not isinstance(payload, dict) or not all(payload.get(k) for k in required):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "Rendered-exposure evidence is incomplete"}), 422
    try:
        row = ProcessingAuthorizationService(db).record_transparency_render(
            acquisition_principal_id=principal_id,
            ai_notice_version=str(payload["ai_notice_version"]),
            surface=str(payload["surface"]),
            client_render_id=str(payload["client_render_id"]),
            rendered_at=str(payload["rendered_at"]),
            client_version=str(payload["client_version"]),
            authenticated_actor_id=(
                str(getattr(request, "user_id", "")) or None
            ),
        )
        return jsonify(row), 201
    except Exception:
        return jsonify({"code": "TRANSPARENCY_RECEIPT_FAILED",
                        "error": "The AI notice receipt could not be recorded"}), 503


@v2_bp.route("/processing-authorization/data-export", methods=["GET"])
@optional_auth
def v2_processing_data_export():
    try:
        principal_id = _principal_id()
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    try:
        data = ProcessingAuthorizationService(db).export_authorization_evidence(
            principal_id
        )
        return jsonify(data), 200
    except Exception:
        return jsonify({"code": "DATA_EXPORT_FAILED",
                        "error": "The data export could not be prepared"}), 503


@v2_bp.route("/processing-authorization/data-rights", methods=["POST"])
@optional_auth
def v2_processing_data_rights():
    try:
        principal_id = _principal_id()
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("request_kind") or "")
    allowed = {"access", "export", "correction", "restriction", "objection"}
    if kind not in allowed:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "Unsupported data-rights request"}), 422
    key = str(payload.get("idempotency_key") or "")
    if not key:
        return jsonify({"code": "IDEMPOTENCY_KEY_REQUIRED",
                        "error": "A request idempotency key is required"}), 422
    subject = payload.get("subject") or {}
    if not isinstance(subject, dict):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "The request subject must be an object"}), 422
    # Raw user text is bounded before it reaches immutable orchestration.
    safe_subject = {
        str(name)[:80]: str(value)[:2000]
        for name, value in subject.items()
        if value is not None
    }
    try:
        row = ProcessingAuthorizationService(db).request_data_right(
            acquisition_principal_id=principal_id,
            request_kind=kind,
            idempotency_key=key,
            subject_payload=safe_subject,
        )
        return jsonify(row), 202
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status


@v2_bp.route("/processing-authorization/terminate", methods=["POST"])
@optional_auth
def v2_processing_terminate():
    try:
        principal_id = _principal_id()
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    payload = request.get_json(silent=True) or {}
    trigger = str(payload.get("trigger_kind") or "service_termination")
    if trigger not in ("service_termination", "account_deletion"):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "Unsupported termination kind"}), 422
    key = str(payload.get("idempotency_key") or "")
    if not key:
        return jsonify({"code": "IDEMPOTENCY_KEY_REQUIRED",
                        "error": "A request idempotency key is required"}), 422
    try:
        row = ProcessingAuthorizationService(db).request_purge(
            acquisition_principal_id=principal_id,
            trigger_kind=trigger,
            idempotency_key=key,
            reason_code=str(payload.get("reason_code") or trigger.upper()),
        )
        return jsonify(row), 202
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status


@v2_bp.route("/processing-authorization/deletion/<purge_id>", methods=["GET"])
@optional_auth
def v2_processing_deletion_status(purge_id: str):
    try:
        principal_id = _principal_id()
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    row = ProcessingAuthorizationService(db).purge_status(principal_id, purge_id)
    if not row:
        return jsonify({"code": "DATA_REQUEST_NOT_FOUND",
                        "error": "Data request not found"}), 404
    return jsonify(row), 200
