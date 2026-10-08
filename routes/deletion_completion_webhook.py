"""Cron entrance for deletions that complete by themselves (founder
2026-10-05, decisions log N48.4: Q14 A, Q17 A; migration 0422).

POST /v2/internal/deletion/complete-due
Header: X-Internal-Secret: DELETION_COMPLETION_SECRET
Body (optional): {"limit": n}  requests to work on this run (1..20, default 10)

Same shape as routes/learning_weekly_webhook.py: no user JWT, one shared
secret, 503 when the secret is not configured, so the surface is DEAD BY
DEFAULT. A Railway cron service is the intended caller
(bin/railway-deletion-completion-cron.sh).

It deletes only when PHASE1_PURGE_EXECUTION_ENABLED is "true" on this
service; otherwise the run is a dry run that reports what is due. Safe to
fire again: one run at a time, and a finished or stopped purge is never run
twice (services/deletion_completion.py).

AC-9. INTERNAL ONLY. The response carries ids, states and reason codes; it
is server-to-server and must never be proxied to a speaker's browser.
"""
from __future__ import annotations

import hmac
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

deletion_completion_webhook_bp = Blueprint("deletion_completion_webhook", __name__)


def _limit(body: object) -> int:
    from services.deletion_completion import DEFAULT_LIMIT, MAX_LIMIT

    raw = body.get("limit") if isinstance(body, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, int):
        return DEFAULT_LIMIT
    return max(1, min(raw, MAX_LIMIT))


@deletion_completion_webhook_bp.route(
    "/v2/internal/deletion/complete-due", methods=["POST"])
def internal_complete_due_deletions():
    from config import Config
    secret = (Config.DELETION_COMPLETION_SECRET or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED",
                        "error": "DELETION_COMPLETION_SECRET not configured"}), 503
    given = (request.headers.get("X-Internal-Secret") or "").strip()
    if not hmac.compare_digest(given, secret):
        return jsonify({"code": "UNAUTHORIZED",
                        "error": "Invalid or missing X-Internal-Secret"}), 401
    from services.db import db
    from services.deletion_completion import run_due_deletions
    execute = Config.PHASE1_PURGE_EXECUTION_ENABLED is True
    try:
        report = run_due_deletions(
            db, execute=execute, limit=_limit(request.get_json(silent=True)))
    except Exception as e:
        logger.error("deletion completion failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR",
                        "error": "The deletion completion run failed."}), 500
    logger.info(
        "deletion completion: mode=%s due=%s processed=%s left_for_a_person=%s",
        report.get("mode"), report.get("due"), len(report.get("outcomes") or []),
        len(report.get("left_for_a_person") or []))
    return jsonify(report), 200
