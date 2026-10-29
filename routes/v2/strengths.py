"""Strengths (Linear WIL-112; founder 2026-10-28, N241; signed N258).
Service: services/strengths.py.

  GET  /v2/strengths                     the Life Panel's list: kept, archived
  POST /v2/strengths/today               the first open of the day before a
                                         talk; {messages}
  GET  /v2/strengths/<id>                the lens: the suggestion and its notes
  POST /v2/strengths/<id>/ask            {choice: look | not_now}; {messages}
  POST /v2/strengths/<id>/decide         {choice: accept | edit | not_now, text?}
  POST /v2/strengths/<id>/archive        the list

A person without strengths gets 404, and nothing from ``today``.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _run(label: str, work):
    from services.strengths import StrengthError
    try:
        return work()
    except StrengthError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("strengths %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the strength"}), 500


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@v2_bp.route("/strengths", methods=["GET"])
@require_auth
def v2_strengths_list():
    from services.strengths import listing
    return _run("list", lambda: (jsonify(listing(db, str(request.user_id))), 200))


@v2_bp.route("/strengths/today", methods=["POST"])
@require_auth
def v2_strengths_today():
    from services.strengths import today
    return _run("today", lambda: (jsonify({"messages": today(db, str(request.user_id))}), 200))


@v2_bp.route("/strengths/<strength_id>", methods=["GET"])
@require_auth
def v2_strengths_suggestion(strength_id):
    from services.strengths import suggestion
    return _run("suggestion", lambda: (jsonify(
        suggestion(db, str(request.user_id), str(strength_id))), 200))


@v2_bp.route("/strengths/<strength_id>/ask", methods=["POST"])
@require_auth
def v2_strengths_ask(strength_id):
    from services.strengths import answer_ask
    choice = str(_body().get("choice") or "")
    return _run("ask", lambda: (jsonify({"messages": answer_ask(
        db, str(request.user_id), str(strength_id), choice)}), 200))


@v2_bp.route("/strengths/<strength_id>/decide", methods=["POST"])
@require_auth
def v2_strengths_decide(strength_id):
    from services.strengths import decide
    body = _body()
    return _run("decide", lambda: (jsonify({"messages": decide(
        db, str(request.user_id), str(strength_id), str(body.get("choice") or ""),
        body.get("text"))}), 200))


@v2_bp.route("/strengths/<strength_id>/archive", methods=["POST"])
@require_auth
def v2_strengths_archive(strength_id):
    from services.strengths import archive
    return _run("archive", lambda: (jsonify(archive(
        db, str(request.user_id), str(strength_id))), 200))
