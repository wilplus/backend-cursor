"""The founder's pace panel (founder 2026-09-30, C9; build plan ML-4).

GET  /v2/admin/learning/ledger      the live ledger, the last weeks, the pace
POST /v2/admin/learning/weekly/run  run the weekly job now (founder only)

Founder only, by email, on top of the admin role: this is a page of
numbers about the machine and the four doors, and nobody else reads it
(AC-9 for everyone else). Nothing here changes a door.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify

from routes.admin import require_founder
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


@v2_bp.route("/admin/learning/ledger", methods=["GET"])
@require_founder
def v2_admin_learning_ledger():
    from services.learning_ledger import ledger as read_ledger
    from services.learning_pace import WINDOW_WEEKS, pace
    from services.exercise_gaps import gap_view
    try:
        live = read_ledger(db)
        # The gap view rode the retired /cms/gaps page (founder 2026-09-30,
        # B8): which pattern needs an exercise filmed, and how many coach
        # requests wait on it. It lives here now so nothing is lost.
        gaps = gap_view(db, days=30)
        # The jar's evaluation rode the retired /cms/jar page (B8, C9, E9;
        # founder 2026-09-29 decision 7, "two piles"): sealed, and why, until
        # the bar (300 attempts, 30 per exercise) is met; then both piles.
        # The live ledger's own count is the gate, so nothing is read twice.
        jar_evaluation = _jar_evaluation(live.get("exercise_jar"))
        snapshots = db.list_ledger_snapshots(limit=WINDOW_WEEKS + 1) or []
        oldest_first = sorted(
            (s for s in snapshots if isinstance(s, dict)),
            key=lambda s: str(s.get("week_start") or ""))
        history = [s.get("snapshot") or {} for s in oldest_first]
        response = jsonify({
            "ledger": live,
            "weeks": [{"week_start": s.get("week_start"), "ready_cues": s.get("ready_cues"),
                       "migration_drafts": s.get("migration_drafts"),
                       "exported": s.get("exported"), "updated_at": s.get("updated_at")}
                      for s in oldest_first],
            "pace": pace(live, history),
            "gaps": gaps,
            "jar_evaluation": jar_evaluation,
        })
        response.headers["Cache-Control"] = "no-store"
        return response, 200
    except Exception as e:
        logger.error("learning ledger read failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to read the ledger"}), 500


def _jar_evaluation(gate):
    """``evaluate_jar`` unchanged, gated on the ledger's own readiness
    (services.exercise_evaluation): sealed and why below the bar, both
    piles above it. None when the jar's count could not be read (the ledger
    names it in ``unavailable``); a failed evaluation is named, never
    served as unsealed."""
    if not isinstance(gate, dict):
        return None
    from services.exercise_evaluation import evaluate_jar
    try:
        return evaluate_jar(db, gate=gate)
    except Exception as e:  # noqa: BLE001 -- the page still serves
        logger.warning("jar evaluation failed: %s", e, exc_info=True)
        return None


@v2_bp.route("/admin/learning/weekly/run", methods=["POST"])
@require_founder
def v2_admin_learning_weekly_run():
    from services.learning_weekly import run_weekly
    try:
        return jsonify(run_weekly(db)), 200
    except Exception as e:
        logger.error("learning weekly (founder) failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "The weekly job failed."}), 500
