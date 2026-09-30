"""Cron entrance for the weekly learning job (founder 2026-09-30; ML-3).

POST /v2/internal/learning/weekly
Header: X-Internal-Secret: LEARNING_WEEKLY_SECRET

Same shape as routes/drift_webhook.py: no user JWT, one shared secret,
503 when the secret is not configured so the surface is DEAD BY DEFAULT.
A Railway cron service is the intended caller, weekly (bin/
railway-learning-weekly-cron.sh).

IDEMPOTENT: one ledger snapshot per ISO week, replaced on a second fire.
The job never trains, exports through a closed door, or promotes: a READY
cue gets its migration text drafted and stored; merging that file after
the founder's go is the promotion (ML-14).

AC-9. INTERNAL ONLY. The response carries counts about the machine; it is
server-to-server and must never be proxied to a speaker's browser.
"""
from __future__ import annotations

import hmac
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

learning_weekly_webhook_bp = Blueprint("learning_weekly_webhook", __name__)


@learning_weekly_webhook_bp.route("/v2/internal/learning/weekly", methods=["POST"])
def internal_run_learning_weekly():
    from config import Config
    secret = (Config.LEARNING_WEEKLY_SECRET or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED",
                        "error": "LEARNING_WEEKLY_SECRET not configured"}), 503
    given = (request.headers.get("X-Internal-Secret") or "").strip()
    if not hmac.compare_digest(given, secret):
        return jsonify({"code": "UNAUTHORIZED",
                        "error": "Invalid or missing X-Internal-Secret"}), 401
    from services.db import db
    from services.learning_weekly import run_weekly
    try:
        report = run_weekly(db)
    except Exception as e:
        logger.error("learning weekly failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR", "error": "The weekly job failed."}), 500
    logger.info("learning weekly: week=%s ready=%s unavailable=%s",
                report.get("week_start"), report.get("ready_cues"),
                report.get("unavailable"))
    return jsonify(report), 200
