"""Cron entrance for the scheduled clean-up (founder 2026-10-05, decisions
log N48.4 Q16 A; services/retention_cleaner.py).

POST /v2/internal/retention/clean
Header: X-Internal-Secret: RETENTION_CLEANER_SECRET
Body:   {"mode": "dry_run"}  -- the default -- or {"mode": "live"}

Same shape as routes/learning_weekly_webhook.py: no user JWT, one shared
secret, 503 when the secret is not configured so the surface is DEAD BY
DEFAULT. A Railway cron service is the intended caller, daily
(bin/railway-retention-cleaner-cron.sh).

The secret only opens the door. Whether anything is deleted is decided by
RETENTION_CLEANER_LIVE in services/retention_cleaner.py, which the founder
sets in a reviewed change after reading a dry run: a live request while it
is False answers 409 with the refused run's record, and nothing is deleted.
Rule 1 (unclaimed guests) is a purge, so a live run erases guests only
while PHASE1_PURGE_EXECUTION_ENABLED is true here, the purge kill switch.

Every answer is a run record: counts by rule, never a person (AC-9).
INTERNAL ONLY: server-to-server, never proxied to a speaker's browser.
"""
from __future__ import annotations

import hmac
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

retention_cleaner_webhook_bp = Blueprint("retention_cleaner_webhook", __name__)


@retention_cleaner_webhook_bp.route("/v2/internal/retention/clean",
                                    methods=["POST"])
def internal_run_retention_cleaner():
    from config import Config
    secret = (Config.RETENTION_CLEANER_SECRET or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED",
                        "error": "RETENTION_CLEANER_SECRET not configured"}), 503
    given = (request.headers.get("X-Internal-Secret") or "").strip()
    if not hmac.compare_digest(given, secret):
        return jsonify({"code": "UNAUTHORIZED",
                        "error": "Invalid or missing X-Internal-Secret"}), 401
    from services.retention_cleaner import parse_mode, run
    body = request.get_json(silent=True)
    try:
        mode = parse_mode((body or {}).get("mode") if isinstance(body, dict) else None)
    except ValueError:
        return jsonify({"code": "MODE_INVALID",
                        "error": "mode is dry_run or live"}), 400
    from services.db import db
    try:
        report = run(db, mode=mode,
                     purge_execution=Config.PHASE1_PURGE_EXECUTION_ENABLED)
    except Exception as e:
        logger.error("retention cleaner failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR",
                        "error": "The clean-up did not run."}), 500
    if report.get("refusal"):
        return jsonify({"code": "LIVE_REFUSED", **report}), 409
    return jsonify(report), 200
