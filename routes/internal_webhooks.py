"""
Server-to-server hooks (no student JWT). Protected by INTERNAL_CREDITS_WEBHOOK_SECRET.
Call from Next.js Stripe webhook or automation after verifying Stripe's signature there.
"""
import logging

from flask import Blueprint, jsonify, request

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()

internal_webhooks_bp = Blueprint("internal_webhooks", __name__)


@internal_webhooks_bp.route("/v2/internal/student-credits/increment", methods=["POST"])
def internal_increment_student_credits():
    """
    Body JSON: { "user_id": "<uuid>", "delta": <int> }
    Header: X-Internal-Secret: <INTERNAL_CREDITS_WEBHOOK_SECRET>

    Example: $50 pack = 10 lessons at 5 credits each → delta: 10 (your product mapping lives in the caller).
    """
    secret = (getattr(config, "INTERNAL_CREDITS_WEBHOOK_SECRET", None) or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED", "error": "INTERNAL_CREDITS_WEBHOOK_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    delta = data.get("delta")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"code": "INVALID_INPUT", "error": "user_id is required"}), 400
    try:
        d = int(delta)
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT", "error": "delta must be an integer"}), 400
    if d == 0:
        details = db.v2_get_student_details(user_id.strip()) or {}
        cur = details.get("credits")
        if cur is None:
            cur = 15
        return jsonify({"status": "ok", "user_id": user_id.strip(), "credits": int(cur), "delta_applied": 0}), 200

    new_bal = db.v2_increment_student_credits(user_id.strip(), d)
    if new_bal is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not update credits"}), 500
    logger.info("internal_increment_student_credits user_id=%s delta=%s new_credits=%s", user_id, d, new_bal)
    return jsonify({"status": "ok", "user_id": user_id.strip(), "credits": new_bal, "delta_applied": d}), 200
