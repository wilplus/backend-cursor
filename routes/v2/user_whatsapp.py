"""The speaker's WhatsApp number for "the feedback from your coach is in"
(founder 2026-10-12). Logic in services/whatsapp_notify.py."""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


@v2_bp.route("/user/whatsapp", methods=["GET", "PUT", "DELETE"])
@require_auth
def v2_user_whatsapp():
    from services.whatsapp_notify import (
        WhatsAppRefusal, remove_phone, save_phone, whatsapp_state,
    )
    try:
        if request.method == "GET":
            return jsonify(whatsapp_state(db, request.user_id)), 200
        if request.method == "DELETE":
            return jsonify(remove_phone(db, request.user_id)), 200
        return jsonify(save_phone(db, request.user_id,
                                  request.get_json(silent=True) or {})), 200
    except WhatsAppRefusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("user/whatsapp %s failed: %s", request.method, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the number"}), 500
