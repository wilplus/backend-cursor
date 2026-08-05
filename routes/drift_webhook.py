"""Cron entrance for the weekly drift run (PM-3).

POST /v2/internal/drift/run
Header: X-Internal-Secret: DRIFT_MONITOR_SECRET

Same shape as routes/life_reminders_webhook.py: no user JWT, one shared
secret, 503 when the secret is not configured so the surface is DEAD BY
DEFAULT. A Railway cron service is the intended caller, weekly.

WHAT IT RETURNS. The PM-3 2x2 per dimension, plus `worst` — the most urgent
verdict across all of them, so an alert can key on one field:

    HEALTHY           nothing moved
    POPULATION_MOVED  inputs shifted, decisions did not
    PIPELINE_CHANGED  inputs stable, DECISIONS drifted — our own code moved,
                      and this is the one the layer exists to catch
    UPSTREAM_CHANGE   both moved: new ASR version, VAD change, segmentation edit
    UNKNOWN           not enough data to say

IDEMPOTENT. The run only reads, except for minting the frozen reference the
first time there is enough data — and `reference_distribution` blocks UPDATE
by trigger, so a double-fired cron cannot overwrite a baseline.

AC-9. INTERNAL ONLY. The response carries PSI values, fire rates and control
limits; none of it may reach a client-facing schema or user-visible copy. This
route is server-to-server and must never be proxied to the browser.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from services import drift_job

logger = logging.getLogger(__name__)

drift_webhook_bp = Blueprint("drift_webhook", __name__)


@drift_webhook_bp.route("/v2/internal/drift/run", methods=["POST"])
def internal_run_drift():
    secret = (os.environ.get("DRIFT_MONITOR_SECRET") or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED",
                        "error": "DRIFT_MONITOR_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED",
                        "error": "Invalid or missing X-Internal-Secret"}), 401

    try:
        weeks = int(request.args.get("weeks") or drift_job.REFERENCE_WEEKS)
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "weeks: must be an integer"}), 400
    weeks = max(1, min(weeks, 52))

    report = drift_job.run_weekly(weeks=weeks)

    worst = report.get("worst")
    # Log at WARNING for anything actionable so it surfaces without a
    # dashboard. PIPELINE_CHANGED is the one worth waking up for: stable
    # inputs with drifting decisions means our own code moved.
    if worst in ("PIPELINE_CHANGED", "UPSTREAM_CHANGE"):
        logger.warning("drift: %s — %s", worst, report.get("dimensions"))
    else:
        logger.info("drift: worst=%s minted=%s note=%s",
                    worst, report.get("minted"), report.get("note"))

    return jsonify(report), 200
