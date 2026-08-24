"""Internal diagnostics and the canonical coach-review publish boundary."""
from __future__ import annotations

import logging
import os

import sentry_sdk
from flask import jsonify, request

from config import Config
from routes.admin import is_admin, require_admin_or_coach
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from services.coach_publish import (
    PublishReviewCommand,
    PublishReviewError,
    publish_reviews,
)
from services.coach_publish_delivery import enqueue_review_delivery
from services.db import db
from utils.errors import safe_error

logger = logging.getLogger(__name__)
config = Config()


@v2_bp.route("/internal/whisper-health", methods=["GET"])
def v2_internal_whisper_health():
    """Report whether transcription credentials and the provider are healthy."""
    try:
        from services.openai_service import OpenAIService

        service = OpenAIService()
        key = config.OPENAI_API_KEY or ""
        reachable = False
        api_error: str | None = None
        model_count = 0
        if service.client:
            try:
                models = service.client.models.list()
                reachable = True
                model_count = len(getattr(models, "data", []) or [])
            except Exception as error:
                api_error = f"{type(error).__name__}: {error}"
        return jsonify({
            "client_initialized": service.client is not None,
            "api_key_present": bool(key),
            "api_key_length": len(key),
            "api_key_prefix": (key[:7] + "...") if key else None,
            "api_reachable": reachable,
            "api_error": api_error,
            "api_model_count": model_count,
            "git_sha": (
                os.environ.get("RAILWAY_GIT_COMMIT_SHA")
                or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            ),
            "env_visible": {
                "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                "BACKEND_URL_INTERNAL": bool(
                    os.environ.get("BACKEND_URL_INTERNAL")
                ),
                "R2_PUBLIC_BASE_URL": bool(
                    os.environ.get("R2_PUBLIC_BASE_URL")
                ),
            },
        }), 200
    except Exception as error:
        logger.error("whisper-health failed: %s", error, exc_info=True)
        return safe_error("INTERNAL_ERROR", 500, exc=error)


def _error_response(error: PublishReviewError):
    return jsonify({"code": error.code, "error": str(error)}), error.status


def publish_complete_reviews(
    payloads,
    *,
    actor_user_id: str,
    admin_override_reason: str | None = None,
):
    """Publish complete snapshots and schedule derived delivery effects.

    This is the shared application boundary for both publish routes. It does
    not save drafts, charge credits, send generic messages, change machine
    processing state, or scan a whole project for Voice Album candidates.
    """
    try:
        commands = [
            PublishReviewCommand.from_payload(payload) for payload in payloads
        ]
        if any(not _is_valid_uuid(command.session_id) for command in commands):
            raise PublishReviewError(
                "INVALID_INPUT", "Every session_id must be a valid UUID", 400,
            )
        results = publish_reviews(
            db,
            commands,
            actor_user_id=str(actor_user_id),
            actor_is_admin=is_admin(str(actor_user_id)),
            admin_override_reason=admin_override_reason,
        )
    except PublishReviewError as error:
        return _error_response(error)
    except Exception as error:
        logger.error(
            "coach review publish failed session=%s: %s",
            [payload.get("session_id") for payload in payloads
             if isinstance(payload, dict)],
            error,
            exc_info=True,
        )
        sentry_sdk.capture_exception(error)
        return jsonify({
            "code": "PUBLISH_FAILED",
            "error": "The review was not published.",
        }), 500

    # The outbox row was committed with the visible revision. A queue outage
    # cannot unpublish it: the periodic sweeper will enqueue this revision.
    body = []
    for command, result in zip(commands, results, strict=True):
        queued = enqueue_review_delivery(result.revision_id)
        body.append({
            "status": "ok",
            "session_id": command.session_id,
            "revision_id": result.revision_id,
            "revision_number": result.revision_number,
            "published_at": result.published_at,
            "replayed": result.replayed,
            "delivery_status": "queued" if queued else "pending",
        })
    return jsonify({"takes": body}), 200


def publish_complete_review(payload, *, actor_user_id: str):
    """Publish one complete review through the same atomic batch boundary."""
    response, status = publish_complete_reviews(
        [payload],
        actor_user_id=actor_user_id,
        admin_override_reason=(
            payload.get("admin_override_reason")
            if isinstance(payload, dict) else None
        ),
    )
    if status != 200:
        return response, status
    take = (response.get_json().get("takes") or [{}])[0]
    return jsonify(take), 200


@v2_bp.route("/internal/publish-session-results", methods=["POST"])
@require_admin_or_coach
def v2_internal_publish_session_results():
    """Publish one immutable, complete professional-review revision."""
    body = request.get_json(silent=True) or {}
    return publish_complete_review(body, actor_user_id=str(request.user_id))
