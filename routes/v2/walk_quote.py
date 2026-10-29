"""The walk quotes your notebook (founder 2026-10-29, N268).
Service: services/walk_quote.py.

  POST /v2/walk-quote            {take_id, said}: the Take's one quote for the
                                 sentence it practises; {quote: {...} | null}
  POST /v2/walk-quote/replay     {take_id}: a walk played again, the quote
                                 it showed; {quote: {...} | null}
  POST /v2/walk-quote/shown      {take_id}: the walk showed it
  GET  /v2/walk-quote/setting    the Life Panel's switch: {available, on}
  POST /v2/walk-quote/setting    {on: bool}: "Not here", or the switch

A person without the ring row or the notebook gets {quote: null} and
{available: false}; a Take that is not theirs, 404.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _run(label: str, work):
    from services.walk_quote import WalkQuoteError
    try:
        return work()
    except WalkQuoteError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("walk_quote %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to read the walk's quote"}), 500


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@v2_bp.route("/walk-quote", methods=["POST"])
@require_auth
def v2_walk_quote_ask():
    from services.walk_quote import ask
    body = _body()
    return _run("ask", lambda: (jsonify({"quote": ask(
        db, str(request.user_id), body.get("take_id"), body.get("said"))}), 200))


@v2_bp.route("/walk-quote/replay", methods=["POST"])
@require_auth
def v2_walk_quote_replay():
    from services.walk_quote import replay
    take_id = _body().get("take_id")
    return _run("replay", lambda: (jsonify({"quote": replay(
        db, str(request.user_id), take_id)}), 200))


@v2_bp.route("/walk-quote/shown", methods=["POST"])
@require_auth
def v2_walk_quote_shown():
    from services.walk_quote import shown
    take_id = _body().get("take_id")
    return _run("shown", lambda: (jsonify(shown(db, str(request.user_id), take_id)), 200))


@v2_bp.route("/walk-quote/setting", methods=["GET"])
@require_auth
def v2_walk_quote_setting():
    from services.walk_quote import setting
    return _run("setting", lambda: (jsonify(setting(db, str(request.user_id))), 200))


@v2_bp.route("/walk-quote/setting", methods=["POST"])
@require_auth
def v2_walk_quote_set():
    from services.walk_quote import set_on
    on = _body().get("on")
    return _run("set", lambda: (jsonify(set_on(db, str(request.user_id), on)), 200))
