"""Cron entrance for the Life Panel's OPT-IN reminders (founder 2026-07-30).

POST /v2/internal/life/reminders?slot=<slot>
Header: X-Internal-Secret: LIFE_REMINDER_SECRET

``slot`` is any rung of the ladder (services/life_reminders.SLOTS): morning,
evening, weekly, monthly, quarterly, yearly, fiveyear, tenyear. The
five/ten-year slots additionally no-op on off years when
LIFE_REMINDER_ANCHOR_YEAR is set (their crons fire yearly; the anchor decides
which years count).

Same shape as the other server-to-server hooks (routes/internal_webhooks.py):
no user JWT, one shared secret, 503 when the secret is not configured so the
surface is dead by default. The Railway cron services (Dockerfile.life-
reminders-cron + bin/railway-life-reminders-cron.sh) are the intended callers,
one service per slot.

This endpoint DELIVERS NOTHING BY ITSELF: services/life_reminders.py reads
only the users whose per-slot switch is ON (all defaults are OFF) and is
idempotent per local day, so a double-fired cron is a no-op. With
LIFE_PANEL_ENABLED off the whole run is skipped — a disabled feature must not
keep a heartbeat.
"""
from __future__ import annotations

import logging
import os

from flask import Blueprint, jsonify, request

from services import life_chat as chat
from services import life_reminders as reminders

logger = logging.getLogger(__name__)

life_reminders_webhook_bp = Blueprint("life_reminders_webhook", __name__)


@life_reminders_webhook_bp.route("/v2/internal/life/reminders",
                                 methods=["POST"])
def internal_run_reminder_slot():
    secret = (os.environ.get("LIFE_REMINDER_SECRET") or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED",
                        "error": "LIFE_REMINDER_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED",
                        "error": "Invalid or missing X-Internal-Secret"}), 401
    if not chat.is_enabled():
        return jsonify({"slot": request.args.get("slot"),
                        "skipped": "LIFE_PANEL_ENABLED is off",
                        "eligible": 0, "sent": 0}), 200
    slot = (request.args.get("slot") or "").strip().lower()
    if slot not in reminders.SLOTS:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "slot: must be one of "
                                 + ", ".join(reminders.SLOTS)}), 400
    result = reminders.run_reminder_slot(slot)
    logger.info("life_reminders: slot=%s eligible=%s sent=%s skipped=%s "
                "failed=%s", slot, result.get("eligible"),
                result.get("sent"), result.get("skipped"),
                result.get("failed"))
    return jsonify(result), 200
