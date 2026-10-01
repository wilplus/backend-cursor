"""Phase 3 of the after-practice paths (founder 2026-10-01, F5): the
speaker's Bold voices read, the once-per-Take steps and the heard receipt.
Every route answers 404 while ``PRAISE_AFTER_PRACTICE_ENABLED`` is off. The
work is ``services.bold_voices``'; the screens are the designer session's.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from services.db import db

logger = logging.getLogger(__name__)


def _run(name: str, take_session_id: str, call):
    if not _is_valid_uuid(take_session_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "take_session_id must be a valid UUID"}), 400
    try:
        status, payload = call()
    except Exception as e:
        logger.error("%s failed take=%s: %s", name, take_session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not do that."}), 500
    return jsonify(payload), status


@v2_bp.route("/user/takes/<take_session_id>/bold-voices", methods=["GET"])
@require_auth
def v2_bold_voices(take_session_id):
    """The speaker's own landed attempts on this Take, the published coach
    readings (no names), and which after-practice steps the Take has shown.
    Plays only: nothing here is judged (Phase 3; migration 0409)."""
    from services.bold_voices import bold_voices_for_take
    return _run("bold-voices", take_session_id, lambda: bold_voices_for_take(
        db, take_session_id=take_session_id, owner_user_id=str(request.user_id)))


@v2_bp.route("/user/takes/<take_session_id>/after-practice-step", methods=["POST"])
@require_auth
def v2_after_practice_step(take_session_id):
    """The Take showed one of the three after-practice steps (bridge, Lend
    your ear, Bold voices); recorded once per Take per step."""
    from services.bold_voices import mark_step
    return _run("after-practice-step", take_session_id, lambda: mark_step(
        db, take_session_id=take_session_id, owner_user_id=str(request.user_id),
        body=request.get_json(silent=True)))


@v2_bp.route("/user/takes/<take_session_id>/bold-voices/heard", methods=["POST"])
@require_auth
def v2_bold_voices_heard(take_session_id):
    """The speaker heard a Bold voices clip: a receipt, nothing judged."""
    from services.bold_voices import record_heard
    return _run("bold-voices-heard", take_session_id, lambda: record_heard(
        db, take_session_id=take_session_id, owner_user_id=str(request.user_id),
        body=request.get_json(silent=True)))
