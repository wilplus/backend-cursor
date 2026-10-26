"""The plan (frontend docs/flows/the-plan.md; N203, N204). Service:
services/plan_flow.py; its rules: services/plan.py.

  GET  /v2/plan                  ?tz=<IANA zone> → {enabled, plan, wrote}
  POST /v2/plan/deadline         {date: "YYYY-MM-DD" | null, tz}
  POST /v2/plan/answer           multipart: audio, duration_ms (a voice answer)
  POST /v2/plan/rating           {value: 1..10}
  GET  /v2/plan/slots            ?which=kickoff|summary&from&to
  POST /v2/plan/call             {which, start: ISO | null, tz}
  PUT  /v2/plan                  {deadline?, days?, tz}
  POST /v2/plan/ask-coach        {}
  POST /v2/plan/next             {choice: keep_practising | new_event, tz}
  POST /v2/plan/new-event        {tz}
  GET  /v2/plan/answers/<id>/audio

Every write answers ``{plan, messages}``: the plan as it now stands and the
rows written to the Lounge thread. A person without the plan (the ring row
``plan``, ring 5) gets enabled false from GET and 404 from the rest. A voice
answer is transcribed, and every AI call runs, under the caller's
processing authorization (``phase1_provider_route``).
"""
import io
import logging
from datetime import timedelta

import sentry_sdk
from flask import jsonify, request, send_file

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.db import db
from services.rate_limits import llm_limit

logger = logging.getLogger(__name__)

MAX_RANGE_DAYS = 62


def _first_name():
    from routes.v2.user_account import _first_name as first
    return first(getattr(request, "token_payload", None))


def _account():
    """The name and email the booking keeps for a call."""
    payload = getattr(request, "token_payload", None) or {}
    meta = payload.get("user_metadata") if isinstance(payload, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    email = str(payload.get("email") or "") if isinstance(payload, dict) else ""
    name = str(meta.get("full_name") or meta.get("name") or "").strip() or email.split("@")[0]
    return name, email


def _run(work):
    """One write: off for this person is 404; a PlanError is its own code."""
    from services.plan_flow import PlanError, enabled, view
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    try:
        out = work(user_id)
        plan = out.get("plan")
        return jsonify({"plan": view(db, user_id, plan) if plan else None,
                        "messages": out.get("messages") or []}), 200
    except PlanError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("plan write failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the answer"}), 500


@v2_bp.route("/plan", methods=["GET"])
@require_auth
def v2_plan_state():
    from services.plan_flow import state
    try:
        return jsonify(state(db, str(request.user_id), tz=request.args.get("tz"),
                             first_name=_first_name())), 200
    except Exception as e:
        logger.error("plan state failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"enabled": False, "plan": None, "wrote": False}), 200


@v2_bp.route("/plan/deadline", methods=["POST"])
@require_auth
def v2_plan_deadline():
    from services.plan_flow import answer_deadline
    body = request.get_json(silent=True) or {}
    return _run(lambda uid: answer_deadline(db, uid, body.get("date"), tz=body.get("tz")))


@v2_bp.route("/plan/answer", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_plan_answer():
    from routes.v2.voice_notebook import _adapter
    from services.plan_flow import answer_voice
    upload = request.files.get("audio")
    if upload is None:
        return jsonify({"code": "EMPTY_AUDIO", "error": "No audio."}), 400
    try:
        duration = int(request.form.get("duration_ms") or 0) or None
    except ValueError:
        duration = None
    audio = upload.read()
    return _run(lambda uid: answer_voice(
        db, uid, _adapter(uid), audio, filename=upload.filename or "answer.webm",
        content_type=upload.mimetype or "audio/webm", duration_ms=duration,
        first_name=_first_name()))


@v2_bp.route("/plan/rating", methods=["POST"])
@require_auth
def v2_plan_rating():
    from services.plan_flow import answer_rating
    body = request.get_json(silent=True) or {}
    return _run(lambda uid: answer_rating(db, uid, body.get("value")))


@v2_bp.route("/plan/slots", methods=["GET"])
@require_auth
def v2_plan_slots():
    from services.plan_flow import PlanError, _parse_dt, call_slots, enabled
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    start, end = _parse_dt(request.args.get("from")), _parse_dt(request.args.get("to"))
    if not start or not end or end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
        return jsonify({"code": "INVALID_RANGE", "error": "from and to must be ISO times"}), 400
    try:
        return jsonify({"slots": call_slots(db, user_id, str(request.args.get("which") or ""),
                                            start, end)}), 200
    except PlanError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.warning("plan slots failed: %s", e, exc_info=True)
        return jsonify({"slots": []}), 200


@v2_bp.route("/plan/call", methods=["POST"])
@require_auth
def v2_plan_call():
    from services.plan_flow import book_call
    body = request.get_json(silent=True) or {}
    name, email = _account()
    return _run(lambda uid: book_call(db, uid, str(body.get("which") or ""), body.get("start"),
                                      tz=body.get("tz"), name=name, email=email))


@v2_bp.route("/plan", methods=["PUT"])
@require_auth
def v2_plan_change():
    from services.plan_flow import change
    body = request.get_json(silent=True) or {}
    return _run(lambda uid: change(db, uid, deadline=body.get("deadline"), days=body.get("days"),
                                   tz=body.get("tz")))


@v2_bp.route("/plan/ask-coach", methods=["POST"])
@require_auth
def v2_plan_ask_coach():
    from services.plan_flow import ask_coach
    return _run(lambda uid: ask_coach(db, uid))


@v2_bp.route("/plan/next", methods=["POST"])
@require_auth
def v2_plan_next():
    from services.plan_flow import next_plan
    body = request.get_json(silent=True) or {}
    return _run(lambda uid: next_plan(db, uid, str(body.get("choice") or ""), tz=body.get("tz"),
                                      first_name=_first_name()))


@v2_bp.route("/plan/new-event", methods=["POST"])
@require_auth
def v2_plan_new_event():
    from services.plan_flow import new_event
    body = request.get_json(silent=True) or {}
    return _run(lambda uid: new_event(db, uid, tz=body.get("tz")))


@v2_bp.route("/plan/answers/<answer_id>/audio", methods=["GET"])
@require_auth
def v2_plan_answer_audio(answer_id):
    from services.plan_flow import PlanError, answer_audio
    try:
        got = answer_audio(db, str(request.user_id), str(answer_id))
    except PlanError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    response = send_file(io.BytesIO(got["audio"]), mimetype=got["content_type"])
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
