"""The proverbial 15 minutes (founder 2026-10-26, N180, N183).
Service: services/fifteen_minutes.py.

  POST /v2/chat/enough-for-today  {day: "YYYY-MM-DD"}; {messages}

The app asks after about 15 minutes in it on one day, at a quiet moment.
Anyone the ring row ``fifteen_minutes`` does not reach gets 404.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


@v2_bp.route("/chat/enough-for-today", methods=["POST"])
@require_auth
def v2_enough_for_today():
    from services.fifteen_minutes import FifteenError, say_enough
    body = request.get_json(silent=True)
    day = body.get("day") if isinstance(body, dict) else None
    try:
        return jsonify({"messages": say_enough(db, str(request.user_id), day)}), 200
    except FifteenError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("enough for today failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to write the line"}), 500
