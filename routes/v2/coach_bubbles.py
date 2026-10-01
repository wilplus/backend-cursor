"""A student's new Take as a bubble in the coach's Lounge chat (founder
2026-10-01, Phase 0c, A2): the Takes in this coach's queue not walked yet.
404 while ``COACH_TAKE_BUBBLES_ENABLED`` is off. The work is
``services.coach_take_bubbles``'; the queue's own gates and loaders are
handed in from ``routes.v2.coach``.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


@v2_bp.route("/coach/take-bubbles", methods=["GET"])
@require_admin_or_coach
def v2_coach_take_bubbles():
    """{bubbles: [{session_id, take_index, sent_at, pseudonym, name?,
    waiting_for_text, first_snippet_id}]}, newest sent first."""
    from routes.v2.coach import (
        _coach_pseudonym, _coach_state_map, _language_matched_rows, _queue_moments_for,
    )
    from services.coach_take_bubbles import take_bubbles
    try:
        status, payload = take_bubbles(
            db, rater_id=str(getattr(request, "user_id", "") or ""),
            state_for=_coach_state_map, matched_rows=_language_matched_rows,
            moments_for_snips=_queue_moments_for, pseudonym_for=_coach_pseudonym)
    except Exception as e:
        logger.error("coach/take-bubbles GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not read the bubbles."}), 500
    return jsonify(payload), status
