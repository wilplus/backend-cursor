"""Post-render acknowledgements for canonical learning surfaces."""
from __future__ import annotations

import logging

from flask import jsonify, request

from auth import require_auth
from routes.admin import is_coach
from routes.v2.blueprint import v2_bp
from services.db import db
from services.learning_exposures import (
    LearningExposureError,
    acknowledge_visible_render,
)


logger = logging.getLogger(__name__)


@v2_bp.route("/learning-exposures/ack", methods=["POST"])
@require_auth
def v2_ack_learning_exposure():
    """Confirm that one prepared packet visibly rendered for this actor."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({
            "code": "INVALID_INPUT", "error": "body must be an object",
        }), 400
    allowed = {
        "presentation_id", "acknowledgement_token", "actor_role",
        "render_instance_id", "client_rendered_at",
    }
    if set(body) - allowed:
        return jsonify({
            "code": "INVALID_INPUT", "error": "unknown acknowledgement field",
        }), 400
    actor_role = str(body.get("actor_role") or "owner")
    actor_id = str(getattr(request, "user_id", "") or "")
    if actor_role == "coach" and not is_coach(actor_id):
        return jsonify({"code": "NOT_FOUND", "error": "Exposure not found"}), 404
    try:
        receipt = acknowledge_visible_render(
            database=db,
            presentation_id=str(body.get("presentation_id") or ""),
            acknowledgement_token=str(
                body.get("acknowledgement_token") or ""),
            actor_role=actor_role,
            actor_id=actor_id,
            render_instance_id=str(body.get("render_instance_id") or ""),
            client_rendered_at=(
                str(body["client_rendered_at"])
                if body.get("client_rendered_at") else None
            ),
        )
        return jsonify({
            "acknowledged": True,
            "exposure_receipt_id": receipt["exposure_receipt_id"],
            "learning_surface": receipt.get("learning_surface"),
            "replayed": bool(receipt.get("replayed")),
        }), 200
    except LearningExposureError as error:
        logger.warning(
            "learning exposure ACK rejected actor=%s role=%s: %s",
            actor_id, actor_role, error,
        )
        return jsonify({
            "code": "EXPOSURE_ACK_REJECTED",
            "error": "Exposure acknowledgement was rejected",
        }), 409
