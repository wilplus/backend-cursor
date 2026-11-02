"""The chats between people, first slice (founder 2026-10-31, N298 to N316).
Service: services/chats.py.

  GET  /v2/chats                  {chats: [{id, kind, title, subtitle,
                                   last: {kind, body, created_at} | null}]}
  GET  /v2/chats/<id>/messages    {messages: [{id, mine, author, kind, body,
                                   meta, created_at}]}, oldest first
  POST /v2/chats/<id>/messages    {kind: "emoji", body: "👍" | "👀" | "🙏"};
                                   {message: {...}}
  POST /v2/chats/demo             makes the two demo chats once; the list

Ring row ``chats`` (ring 6): a person without it gets 404 from every route,
as a chat they are not in does. Anything but the three emoji is 400. No
provider call: nothing here passes the processing-authorization path.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _run(label: str, work):
    """One answer for every route: the service's error as it is, anything
    else a 500 that is logged."""
    from services.chats import ChatsError
    try:
        return jsonify(work()), 200
    except ChatsError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("chats %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to reach the chats"}), 500


@v2_bp.route("/chats", methods=["GET"])
@require_auth
def v2_chats_list():
    from services.chats import list_chats
    return _run("list", lambda: list_chats(db, str(request.user_id)))


@v2_bp.route("/chats/<thread_id>/messages", methods=["GET"])
@require_auth
def v2_chats_read(thread_id):
    from services.chats import read
    return _run("read", lambda: read(db, str(request.user_id), thread_id))


@v2_bp.route("/chats/<thread_id>/messages", methods=["POST"])
@require_auth
def v2_chats_post(thread_id):
    from services.chats import post
    body = request.get_json(silent=True)
    return _run("post", lambda: post(db, str(request.user_id), thread_id, body))


@v2_bp.route("/chats/demo", methods=["POST"])
@require_auth
def v2_chats_demo():
    from services.chats import seed_demo
    return _run("demo", lambda: seed_demo(db, str(request.user_id)))
