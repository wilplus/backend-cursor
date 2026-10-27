"""How many people reach the sign-up screen and how many make an account
(founder 2026-10-26, N207 item 6). Logic in services/signup_count.py.

  POST /v2/signup/seen                 the sign-up screen opened (no sign-in)
  GET  /v2/admin/signup-counts?days=   the founder's counts, newest day first

The first needs no sign-in, because the screen is shown to people without
an account; it keeps a number a day and nothing about the caller, and it is
rate-limited by IP address so one browser cannot inflate it.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_admin
from routes.v2.blueprint import v2_bp
from services.db import db
from services.rate_limits import client_ip, limiter

logger = logging.getLogger(__name__)


@v2_bp.route("/signup/seen", methods=["POST"])
@limiter.limit("20 per hour", key_func=client_ip, scope="signup_seen")
def v2_signup_seen():
    from services import signup_count
    signup_count.seen(db)
    return jsonify({}), 200


@v2_bp.route("/admin/signup-counts", methods=["GET"])
@require_admin
def v2_admin_signup_counts():
    from services import signup_count
    try:
        days = int(request.args.get("days") or 30)
    except ValueError:
        days = 30
    try:
        return jsonify(signup_count.counts(db, days=days)), 200
    except Exception as e:
        logger.error("admin/signup-counts failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not read the counts"}), 500
