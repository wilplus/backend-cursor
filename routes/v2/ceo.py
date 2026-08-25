"""Admin-only API for CEO, the observational Product/Research abstract."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes.admin import require_admin
from services import ceo
from utils.errors import safe_error


ceo_bp = Blueprint("ceo", __name__)


def _no_store(payload: dict, status: int = 200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


@ceo_bp.route("/v2/admin/ceo/bootstrap", methods=["GET"])
@require_admin
def ceo_bootstrap():
    admin_user_id = str(getattr(request, "user_id", "") or "")
    try:
        return _no_store(ceo.get_bootstrap(admin_user_id))
    except Exception as exc:
        return safe_error(
            "CEO_BOOTSTRAP_ERROR",
            500,
            exc=exc,
            log=f"ceo: bootstrap failed admin={admin_user_id}",
        )


@ceo_bp.route(
    "/v2/admin/ceo/projects/<project_key>/view-state", methods=["PATCH"]
)
@require_admin
def ceo_view_state(project_key: str):
    admin_user_id = str(getattr(request, "user_id", "") or "")
    try:
        saved = ceo.save_view_state(
            admin_user_id,
            project_key,
            request.get_json(silent=True),
        )
        return _no_store({"view_state": saved})
    except ceo.CeoValidationError as exc:
        return _no_store({
            "code": "INVALID_CEO_VIEW_STATE",
            "error": str(exc),
        }, 400)
    except Exception as exc:
        return safe_error(
            "CEO_VIEW_STATE_ERROR",
            500,
            exc=exc,
            log=f"ceo: view state failed admin={admin_user_id}",
        )


@ceo_bp.route(
    "/v2/admin/ceo/projects/<project_key>/features", methods=["POST"]
)
@require_admin
def ceo_create_feature(project_key: str):
    admin_user_id = str(getattr(request, "user_id", "") or "")
    try:
        return _no_store(
            ceo.create_feature(
                admin_user_id,
                project_key,
                request.get_json(silent=True),
            ),
            201,
        )
    except ceo.CeoValidationError as exc:
        return _no_store({
            "code": "INVALID_CEO_FEATURE",
            "error": str(exc),
        }, 400)
    except Exception as exc:
        return safe_error(
            "CEO_FEATURE_CREATE_ERROR",
            500,
            exc=exc,
            log=f"ceo: feature create failed admin={admin_user_id}",
        )


@ceo_bp.route("/v2/admin/ceo/artifacts/<artifact_id>", methods=["PATCH"])
@require_admin
def ceo_save_artifact(artifact_id: str):
    admin_user_id = str(getattr(request, "user_id", "") or "")
    try:
        return _no_store(
            ceo.save_artifact_revision(
                admin_user_id,
                artifact_id,
                request.get_json(silent=True),
            )
        )
    except ceo.CeoValidationError as exc:
        return _no_store({
            "code": "INVALID_CEO_ARTIFACT",
            "error": str(exc),
        }, 400)
    except ceo.CeoConflictError as exc:
        return _no_store({
            "code": "CEO_ARTIFACT_CONFLICT",
            "error": str(exc),
        }, 409)
    except Exception as exc:
        return safe_error(
            "CEO_ARTIFACT_SAVE_ERROR",
            500,
            exc=exc,
            log=f"ceo: artifact save failed admin={admin_user_id}",
        )


@ceo_bp.route(
    "/v2/admin/ceo/artifacts/<artifact_id>/comments", methods=["POST"]
)
@require_admin
def ceo_comment_artifact(artifact_id: str):
    admin_user_id = str(getattr(request, "user_id", "") or "")
    try:
        return _no_store(
            ceo.comment_and_request_reevaluation(
                admin_user_id,
                artifact_id,
                request.get_json(silent=True),
            ),
            202,
        )
    except ceo.CeoValidationError as exc:
        return _no_store({
            "code": "INVALID_CEO_COMMENT",
            "error": str(exc),
        }, 400)
    except Exception as exc:
        return safe_error(
            "CEO_ARTIFACT_COMMENT_ERROR",
            500,
            exc=exc,
            log=f"ceo: artifact comment failed admin={admin_user_id}",
        )
