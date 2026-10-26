"""Life goals (Will learning plan, step 3; founder 2026-10-26, N172).
Service: services/life_goals.py.

  GET  /v2/life-goals                    {enabled, goals, draft}
  POST /v2/life-goals/ask                {choice: start | not_now}
  POST /v2/life-goals/transcribe         multipart: audio; {text}
  POST /v2/life-goals/draft              {space, answers}; {goal, quotes}
  POST /v2/life-goals/redraft            {space, goal, under}; {goal, quote}
  PUT  /v2/life-goals/drafts             {id?, space, ladder}; the draft
  POST /v2/life-goals/<id>/finish        {replaces?}; {messages}
  POST /v2/life-goals/<id>/steps         {step, text}; the goal

A person without life goals gets enabled false from the first and 404 from
the rest. Transcription and Will's drafts run under the caller's processing
authorization (``phase1_provider_route``), like the chat.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.db import db
from services.rate_limits import llm_limit

logger = logging.getLogger(__name__)


def _error(e):
    return jsonify({"code": e.code, "error": str(e)}), e.status


def _run(label: str, work):
    """One answer for every route: the service's error as it is, anything
    else a 500 that is logged."""
    from services.life_goals import GoalsError
    try:
        return work()
    except GoalsError as e:
        return _error(e)
    except Exception as e:
        logger.error("life goals %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the goal"}), 500


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@v2_bp.route("/life-goals", methods=["GET"])
@require_auth
def v2_life_goals_state():
    from services.life_goals import state
    return _run("state", lambda: (jsonify(state(db, str(request.user_id))), 200))


@v2_bp.route("/life-goals/ask", methods=["POST"])
@require_auth
def v2_life_goals_ask():
    from services.life_goals import answer
    choice = str(_body().get("choice") or "")
    return _run("ask", lambda: (jsonify(
        {"messages": answer(db, str(request.user_id), choice)}), 200))


@v2_bp.route("/life-goals/transcribe", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_life_goals_transcribe():
    from routes.v2.voice_notebook import _adapter
    from services.life_goals import transcribe
    user_id = str(request.user_id)
    upload = request.files.get("audio")
    if upload is None:
        return jsonify({"code": "EMPTY_AUDIO", "error": "No audio."}), 400
    return _run("transcribe", lambda: (jsonify({"text": transcribe(
        db, user_id, _adapter(user_id), upload.read(),
        filename=upload.filename or "answer.webm")}), 200))


@v2_bp.route("/life-goals/draft", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_life_goals_draft():
    from services.life_goals import draft
    body = _body()
    return _run("draft", lambda: (jsonify(draft(
        db, str(request.user_id), str(body.get("space") or ""),
        body.get("answers"))), 200))


@v2_bp.route("/life-goals/redraft", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_life_goals_redraft():
    from services.life_goals import redraft
    body = _body()
    return _run("redraft", lambda: (jsonify(redraft(
        db, str(request.user_id), str(body.get("space") or ""),
        body.get("goal"), body.get("under"))), 200))


@v2_bp.route("/life-goals/drafts", methods=["PUT"])
@require_auth
def v2_life_goals_save_draft():
    from services.life_goals import enabled, save_draft
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    body = _body()
    return _run("draft save", lambda: (jsonify(save_draft(
        user_id, str(body["id"]) if body.get("id") else None,
        str(body.get("space") or ""), body.get("ladder"))), 200))


@v2_bp.route("/life-goals/<goal_id>/finish", methods=["POST"])
@require_auth
def v2_life_goals_finish(goal_id):
    from services.life_goals import finish
    replaces = _body().get("replaces")
    return _run("finish", lambda: (jsonify({"messages": finish(
        db, str(request.user_id), str(goal_id),
        str(replaces) if replaces else None)}), 200))


@v2_bp.route("/life-goals/<goal_id>/steps", methods=["POST"])
@require_auth
def v2_life_goals_change_step(goal_id):
    from services.life_goals import change_step
    body = _body()
    return _run("step", lambda: (jsonify(change_step(
        db, str(request.user_id), str(goal_id), str(body.get("step") or ""),
        body.get("text"))), 200))
