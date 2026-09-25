"""The training switch: GET, turn on (POST), turn off (DELETE). DARK.

SPEC-training-corpus §3; the logic and the refusals live in
``services.training_consent``. Answers 410 while
``Config.MLC2_TRAINING_SWITCH_ENABLED`` is False, which it is until P5.
Responses carry codes only; the words are the frontend's, signed by the
founder (N10).
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db
from services.project_repository import ProjectOwnershipError, ProjectRepository
from services.training_consent import (
    TrainingSwitchError, handle, switch_enabled,
)

logger = logging.getLogger(__name__)
_repository = ProjectRepository(db)
_CLIENT_VERSION_FALLBACK = "willab-web-unknown"


def _client_version() -> str:
    value = str(request.headers.get("X-Willab-Client-Version")
                or _CLIENT_VERSION_FALLBACK).strip()
    return value[:120] or _CLIENT_VERSION_FALLBACK


@v2_bp.route("/user/training-consent", methods=["GET", "POST", "DELETE"])
@require_auth
def v2_user_training_consent():
    if not switch_enabled():
        return jsonify({"code": "TRAINING_SWITCH_DISABLED"}), 410
    try:
        owner = _repository.owner_for_user(
            str(getattr(request, "user_id", "")).strip())
        state = handle(db, owner.id, request.method,
                       request.get_json(silent=True), _client_version())
        return jsonify(state), 200
    except TrainingSwitchError as error:
        return jsonify({"code": error.code}), error.status
    except ProjectOwnershipError as error:
        logger.error("training switch owner resolution failed: %s", error)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "PRINCIPAL_UNAVAILABLE"}), 503
    except Exception as error:
        logger.error("training switch failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "TRAINING_SWITCH_FAILED"}), 500
