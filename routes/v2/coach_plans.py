"""The coach's side of the plan (N213; frontend docs/flows/the-plan.md and
docs/flows/coach-panel.md). A plan reaches the queue on its speaker's card
(``routes.v2.coach``, the moments queue); these open it. The work is
``services.plan_coach``'; the queue's own language gate is handed in from
``routes.v2.coach``.

  GET  /v2/coach/plans/<plan_id>                 the plan to answer: blind
  POST /v2/coach/plans/<plan_id>/level           {level} → What happened
  POST /v2/coach/plans/<plan_id>/answered        a stuck level's video, shared
  POST /v2/coach/plans/<plan_id>/unclear         Audio unclear
  GET  /v2/coach/plans/<plan_id>/answers/<answer_id>/audio
"""
from __future__ import annotations

import io
import logging

import sentry_sdk
from flask import jsonify, request, send_file

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from services.db import db

logger = logging.getLogger(__name__)


def _rater() -> str:
    return str(getattr(request, "user_id", "") or "")


def _open(plan_id: str, *, own_answer: bool = False):
    """``(plan, kind, None)`` when this coach may see the plan, else
    ``(None, None, response)``: the same language gate as the queue, read
    for this plan's speaker only."""
    from routes.v2.coach import _language_matched_rows, _rater_language_error
    from services.coach_queue import load_review_queue
    from services.plan_coach import CoachPlanError, plan_for
    if not _is_valid_uuid(plan_id):
        return None, None, (jsonify({"code": "INVALID_INPUT", "error": "plan_id must be a UUID"}), 400)
    proficient = db.get_user_proficient_languages(_rater())
    if not proficient:
        return None, None, _rater_language_error("profile_required")
    plan = db.get_plan_by_id(plan_id)
    rows, snips, _states = load_review_queue(db, snippets=False) if plan else ([], {}, {})
    rows = [r for r in rows if str(r.get("user_id")) == str((plan or {}).get("user_id"))]
    users = {str(r.get("user_id")) for r in rows}
    matched = {str(r.get("user_id")) for r in _language_matched_rows(rows, snips, proficient)}
    try:
        plan, kind = plan_for(db, plan, rater_id=_rater(), proficient=proficient,
                              matched_users=matched, queued_users=users, own_answer=own_answer)
    except CoachPlanError as e:
        return None, None, (jsonify({"code": e.code, "error": str(e)}), e.status)
    return plan, kind, None


def _run(name: str, plan_id: str, call, *, own_answer: bool = False):
    from services.plan_coach import CoachPlanError
    try:
        plan, kind, refused = _open(plan_id, own_answer=own_answer)
        if refused:
            return refused
        return jsonify(call(plan, kind)), 200
    except CoachPlanError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("%s failed plan=%s: %s", name, plan_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not do that."}), 500


@v2_bp.route("/coach/plans/<plan_id>", methods=["GET"])
@require_admin_or_coach
def v2_coach_plan(plan_id):
    """"Which level comes first?" (the voice message, the key line and the
    five levels, never the plan's level: Never 2), or a stuck level's video
    screen (its name and the Take the video goes on)."""
    from services.coach_pseudonym import coach_pseudonym
    from services.plan_coach import blind
    return _run("coach/plans GET", plan_id, lambda plan, kind: blind(
        db, plan, kind, pseudonym=coach_pseudonym(plan.get("user_id"))))


@v2_bp.route("/coach/plans/<plan_id>/level", methods=["POST"])
@require_admin_or_coach
def v2_coach_plan_level(plan_id):
    """The coach's level, kept as theirs (C5); "What happened" comes with
    it, never before (Never 2). "Change my answer" posts again."""
    from services.plan_coach import pick
    body = request.get_json(silent=True)
    level = body.get("level") if isinstance(body, dict) else None
    return _run("coach/plans level", plan_id, lambda plan, kind: pick(
        db, plan, kind, level, rater_id=_rater()), own_answer=True)


@v2_bp.route("/coach/plans/<plan_id>/answered", methods=["POST"])
@require_admin_or_coach
def v2_coach_plan_answered(plan_id):
    """A stuck level's video, shared as the coach's word on the speaker's
    latest Take (``PUT /v2/coach/sessions/<id>/word``): the plan leaves the
    queue."""
    from services.plan_coach import answered
    return _run("coach/plans answered", plan_id, lambda plan, kind: answered(
        db, plan, kind, rater_id=_rater()), own_answer=True)


@v2_bp.route("/coach/plans/<plan_id>/unclear", methods=["POST"])
@require_admin_or_coach
def v2_coach_plan_unclear(plan_id):
    """Audio unclear: the plan leaves this coach's queue only."""
    from services.plan_coach import unclear
    return _run("coach/plans unclear", plan_id, lambda plan, _kind: unclear(
        db, plan, rater_id=_rater()))


@v2_bp.route("/coach/plans/<plan_id>/answers/<answer_id>/audio", methods=["GET"])
@require_admin_or_coach
def v2_coach_plan_answer_audio(plan_id, answer_id):
    """The voice message or the key line, played; no other answer."""
    from services.plan_coach import CoachPlanError, answer_audio
    if not _is_valid_uuid(answer_id):
        return jsonify({"code": "INVALID_INPUT", "error": "answer_id must be a UUID"}), 400
    try:
        plan, _kind, refused = _open(plan_id, own_answer=True)
        if refused:
            return refused
        got = answer_audio(db, plan, answer_id)
    except CoachPlanError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("coach/plans audio failed plan=%s: %s", plan_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not play that."}), 500
    response = send_file(io.BytesIO(got["audio"]), mimetype=got["content_type"])
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
