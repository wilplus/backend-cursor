"""Your why, every day (founder 2026-10-29, N255; signed N258).
Service: services/your_why.py.

  GET  /v2/your-why                 the three lines, their changes and history
  POST /v2/your-why/today           the first open of the day: the ask, or the
                                    day's why; {messages}
  POST /v2/your-why/ask             {choice: start | not_now}; {messages}
  POST /v2/your-why/draft           {answers: {why, vision, treat}}; the drafts
  POST /v2/your-why                 {lines: {why, vision, treat}}; {messages}
  POST /v2/your-why/<line>          {text}; the state

A person without it gets 404, and nothing from ``today``. Will's drafts run
under the caller's processing authorization (``phase1_provider_route``),
like the chat.
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


def _run(label: str, work):
    """One answer for every route: the service's error as it is, anything
    else a 500 that is logged."""
    from services.your_why import WhyError
    try:
        return work()
    except WhyError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("your why %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep your why"}), 500


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@v2_bp.route("/your-why", methods=["GET"])
@require_auth
def v2_your_why_state():
    from services.your_why import state
    return _run("state", lambda: (jsonify(state(db, str(request.user_id))), 200))


@v2_bp.route("/your-why/today", methods=["POST"])
@require_auth
def v2_your_why_today():
    from services.your_why import today
    return _run("today", lambda: (jsonify({"messages": today(db, str(request.user_id))}), 200))


@v2_bp.route("/your-why/ask", methods=["POST"])
@require_auth
def v2_your_why_ask():
    from services.your_why import answer_ask
    choice = str(_body().get("choice") or "")
    return _run("ask", lambda: (jsonify(
        {"messages": answer_ask(db, str(request.user_id), choice)}), 200))


@v2_bp.route("/your-why/draft", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_your_why_draft():
    from services.your_why import draft
    answers = _body().get("answers")
    return _run("draft", lambda: (jsonify(draft(db, str(request.user_id), answers)), 200))


@v2_bp.route("/your-why", methods=["POST"])
@require_auth
def v2_your_why_save():
    from services.your_why import save
    lines = _body().get("lines")
    return _run("save", lambda: (jsonify({"messages": save(db, str(request.user_id), lines)}), 200))


@v2_bp.route("/your-why/<line>", methods=["POST"])
@require_auth
def v2_your_why_change(line):
    from services.your_why import change
    text = _body().get("text")
    return _run("change", lambda: (jsonify(change(db, str(request.user_id), str(line), text)), 200))
