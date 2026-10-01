"""The coach's blind lines (founder 2026-10-01; migration 0411): the error
audit (6a, F6) and the block pick (8, C5-b). Each lists this coach's pending
items, sampled on the read up to the shared weekly cap, and takes one answer
per item, once. Nothing here says what the detector or the Manager chose.
Every route answers 404 while its constant is off. The work is
``services.error_presence_audit`` and ``services.coach_block_pick``'.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _run(name: str, call):
    try:
        status, payload = call()
    except Exception as e:
        logger.error("%s failed: %s", name, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not do that."}), 500
    return jsonify(payload), status


def _coach_id() -> str:
    return str(getattr(request, "user_id", "") or "")


@v2_bp.route("/coach/error-audit", methods=["GET"])
@require_admin_or_coach
def v2_coach_error_audit_queue():
    """This coach's pending blind error checks, sampled up to the cap."""
    from services.error_presence_audit import audit_enabled, queue, sample_for_coach

    def call():
        if audit_enabled():
            sample_for_coach(db, coach_id=_coach_id())
        return queue(db, coach_id=_coach_id())
    return _run("error audit queue", call)


@v2_bp.route("/coach/error-audit/<audit_id>/answer", methods=["POST"])
@require_admin_or_coach
def v2_coach_error_audit_answer(audit_id):
    """Body {answer: yes | no | cant_tell}: one answer, once."""
    from services.error_presence_audit import answer
    return _run("error audit answer", lambda: answer(
        db, coach_id=_coach_id(), audit_id=str(audit_id),
        body=request.get_json(silent=True)))


@v2_bp.route("/coach/block-picks", methods=["GET"])
@require_admin_or_coach
def v2_coach_block_picks_queue():
    """This coach's pending block picks, sampled up to the shared cap."""
    from services.coach_block_pick import block_pick_enabled, queue, sample_for_coach
    from services.error_presence_audit import week_key

    def call():
        if block_pick_enabled():
            sample_for_coach(db, coach_id=_coach_id(), week=week_key())
        return queue(db, coach_id=_coach_id())
    return _run("block pick queue", call)


@v2_bp.route("/coach/block-picks/<pick_id>/answer", methods=["POST"])
@require_admin_or_coach
def v2_coach_block_pick_answer(pick_id):
    """Body {pick_clip_id} or {cant_tell: true}: one pick, once."""
    from services.coach_block_pick import answer
    return _run("block pick answer", lambda: answer(
        db, coach_id=_coach_id(), pick_id=str(pick_id),
        body=request.get_json(silent=True)))
