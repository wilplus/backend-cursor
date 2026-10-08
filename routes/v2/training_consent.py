"""The training switch: GET, turn on (POST), turn off (DELETE).

SPEC-training-corpus §3; the logic and the refusals live in
``services.training_consent``. Door 1 is OPEN since 2026-10-01 (the
founder's sentence "open door 1"; docs/LEARNING-DOORS.md):
``Config.MLC2_TRAINING_SWITCH_ENABLED`` is True, so the route answers. It
answers 410 only if a reviewed change sets the constant back to False.
While no training policy row is active it answers ``available: false`` and
the Settings card hides itself. Responses carry codes only; the words are
the frontend's, signed by the founder (N10). Refusals are reported to
Sentry by code, never with a person's id.

The speaker identity is computed here, from the verified token, and handed
to the switch: the training yes binds the speaker it admits into the
confidence chain (founder 2026-10-05, N48.5 Q27 A; migration 0430).
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db
from services.project_repository import ProjectOwnershipError, ProjectRepository
from services.speaker_identity import identity_coordinates
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
        user_id = str(getattr(request, "user_id", "")).strip()
        owner = _repository.owner_for_user(user_id)
        identity = identity_coordinates(
            getattr(request, "token_payload", None) or {}, user_id)
        state = handle(db, owner.id, request.method,
                       request.get_json(silent=True), _client_version(),
                       identity=identity)
        return jsonify(state), 200
    except TrainingSwitchError as error:
        logger.warning("training switch refused: %s", error.code)
        sentry_sdk.capture_message(
            f"training switch refused: {error.code}", level="warning")
        return jsonify({"code": error.code}), error.status
    except ProjectOwnershipError as error:
        logger.error("training switch owner resolution failed: %s", error)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "PRINCIPAL_UNAVAILABLE"}), 503
    except Exception as error:
        logger.error("training switch failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "TRAINING_SWITCH_FAILED"}), 500
