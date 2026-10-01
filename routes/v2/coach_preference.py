"""Phase 1b of the coach panel (founder 2026-10-01, F8): the coach keeps,
swaps or replaces the exercise the machine served, and that explicit choice
is recorded as the coach's preference. Behind the blind gate (the coach has
rated the moment first) and 404 while ``COACH_EXERCISE_PREFERENCE_ENABLED``
is off. The work is ``services.coach_exercise_preference``'.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _gate(session_id, snippet_id):
    from routes.v2.coach import _moment_gate
    return _moment_gate(session_id, snippet_id)


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-preference",
    methods=["GET"],
)
@require_admin_or_coach
def v2_coach_exercise_preference_read(session_id, snippet_id):
    """What the machine served on this moment and the pool it could swap
    to, shuffled, no rank, the served one marked; 404 off or when nothing
    was served."""
    from services.coach_exercise_preference import preference_enabled, served_view
    error, owner_sid = _gate(session_id, snippet_id)
    if error:
        return error
    if not preference_enabled():
        return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
    try:
        view = served_view(db, take_session_id=owner_sid, snippet_id=snippet_id)
    except Exception as e:
        logger.error("exercise preference read failed sid=%s snip=%s: %s",
                     session_id, snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not read this."}), 500
    if view is None:
        return jsonify({"code": "NO_SERVED_EXERCISE",
                        "error": "The machine served no exercise on this moment."}), 404
    return jsonify({"served": view["served"], "pool": view["pool"]}), 200


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-preference",
    methods=["POST"],
)
@require_admin_or_coach
def v2_coach_exercise_preference_record(session_id, snippet_id):
    """Body {action: kept | swapped | new, chosen_exercise_id?}: one explicit
    choice, appended; silence records nothing."""
    from services.coach_exercise_preference import record
    error, owner_sid = _gate(session_id, snippet_id)
    if error:
        return error
    session = db.v2_get_session_by_id(owner_sid) or {}
    try:
        status, payload = record(
            db, coach_id=str(getattr(request, "user_id", "")),
            take_session_id=owner_sid, snippet_id=snippet_id,
            speaker_user_id=session.get("user_id"),
            body=request.get_json(silent=True))
    except Exception as e:
        logger.error("exercise preference record failed sid=%s snip=%s: %s",
                     session_id, snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not record this."}), 500
    return jsonify(payload), status
