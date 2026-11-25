"""A person's own chats: one kind of chat, decided by use (founder, N700).

  GET    /v2/user/own-chats                 the list, the newest used first
  POST   /v2/user/own-chats                 {title?} a new chat
  PATCH  /v2/user/own-chats/<id>            {title} rename
  POST   /v2/user/own-chats/<id>/project    {arc_id} the chat's first Take or
                                            slides give it its project

The messages of one chat: GET /v2/user/lounge/messages?own=<id> (lounge.py).
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)

_NOT_FOUND = ({"code": "NOT_FOUND", "error": "Not found."}, 404)


def _shape(chat: dict) -> dict:
    return {
        "id": str(chat.get("id")),
        "title": chat.get("title") or "",
        "arc_id": str(chat["arc_id"]) if chat.get("arc_id") else None,
        "section": chat.get("legacy_place"),
        "created_at": chat.get("created_at"),
        "last_used_at": chat.get("last_used_at"),
    }


@v2_bp.route("/user/own-chats", methods=["GET"])
@require_auth
def v2_own_chats_list():
    from services import own_chats
    try:
        return jsonify({"chats": [_shape(c) for c in own_chats.list_chats(db, request.user_id)]}), 200
    except Exception as error:  # noqa: BLE001
        logger.error("own-chats list failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load chats"}), 500


@v2_bp.route("/user/own-chats", methods=["POST"])
@require_auth
def v2_own_chats_create():
    from services import own_chats
    body = request.get_json(silent=True) or {}
    made = own_chats.create_chat(db, request.user_id, body.get("title"))
    if not made:
        return jsonify({"code": "V2_ERROR", "error": "Failed to make the chat"}), 500
    own_chats.touch(db, request.user_id, made.get("id"))
    return jsonify({"chat": _shape(made)}), 201


@v2_bp.route("/user/own-chats/<chat_id>", methods=["PATCH"])
@require_auth
def v2_own_chats_rename(chat_id):
    from services import own_chats
    body = request.get_json(silent=True) or {}
    if not own_chats.clean_title(body.get("title")):
        return jsonify({"code": "INVALID_INPUT", "error": "title: 1 to 200 characters"}), 400
    renamed = own_chats.rename_chat(db, request.user_id, chat_id, body.get("title"))
    if not renamed:
        return jsonify(_NOT_FOUND[0]), _NOT_FOUND[1]
    return jsonify({"chat": _shape(renamed)}), 200


@v2_bp.route("/user/own-chats/<chat_id>/project", methods=["POST"])
@require_auth
def v2_own_chats_project(chat_id):
    """The chat's project, from its first Take or slides. Only a project of
    the caller's own; a chat that has one keeps it."""
    from services import own_chats
    from services.user_trainings import list_trainings
    body = request.get_json(silent=True) or {}
    arc = str(body.get("arc_id") or "")
    mine = {str(p.get("arc_id")) for p in (list_trainings(db, request.user_id, every_project=False) or []) if isinstance(p, dict)}
    if not arc or arc not in mine:
        return jsonify(_NOT_FOUND[0]), _NOT_FOUND[1]
    chat = own_chats.attach_project(db, request.user_id, chat_id, arc)
    if not chat:
        return jsonify(_NOT_FOUND[0]), _NOT_FOUND[1]
    return jsonify({"chat": _shape(chat)}), 200
