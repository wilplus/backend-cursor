"""Where people leave between the landing page and their first feedback
(founder 2026-10-29, N271). Logic in services/first_visit.py.

  POST /v2/first-visit/step {"step"}      a visitor reached a step (no sign-in)
  GET  /v2/admin/first-visit-counts?days= the founder's path, newest day first

The first needs no sign-in, because the steps happen before there is an
account; it keeps a number a day and nothing about the caller, and it is
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


@v2_bp.route("/first-visit/step", methods=["POST"])
@limiter.limit("60 per hour", key_func=client_ip, scope="first_visit_step")
def v2_first_visit_step():
    from services import first_visit
    body = request.get_json(silent=True) or {}
    if not first_visit.step(db, str(body.get("step") or "")):
        return jsonify({"code": "UNKNOWN_STEP", "error": "Unknown step"}), 400
    return jsonify({}), 200


@v2_bp.route("/admin/first-visit-counts", methods=["GET"])
@require_admin
def v2_admin_first_visit_counts():
    from services import first_visit
    try:
        days = int(request.args.get("days") or 30)
    except ValueError:
        days = 30
    try:
        return jsonify(first_visit.counts(db, days=days)), 200
    except Exception as e:
        logger.error("admin/first-visit-counts failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not read the counts"}), 500
