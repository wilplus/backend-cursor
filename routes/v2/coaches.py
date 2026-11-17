"""The speaking-coach document (services/coach_definition.py).

Behind the chat_builder ring, like the rest of the builder. Publish is
the founder's. Preview writes nothing.
"""
from __future__ import annotations

import logging

from flask import jsonify, request

from auth import require_auth
from routes.admin import require_founder
from routes.v2.blueprint import v2_bp
from services import assistants, coach_definition as coach
from services.db import db

logger = logging.getLogger(__name__)


def _ring():
    if not assistants.on(db, str(request.user_id)):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    return None


def _refused(error: coach.CoachRefused):
    return jsonify({"code": error.code}), 400


@v2_bp.route("/coaches/speaking-coach", methods=["GET"])
@require_auth
def v2_coach_draft():
    blocked = _ring()
    if blocked:
        return blocked
    return jsonify({"document": coach.read_draft(db, str(request.user_id))}), 200


@v2_bp.route("/coaches/speaking-coach/draft", methods=["PUT"])
@require_auth
def v2_coach_save():
    blocked = _ring()
    if blocked:
        return blocked
    body = request.get_json(silent=True) or {}
    try:
        saved = coach.save_draft(db, str(request.user_id), body.get("document"))
    except coach.CoachRefused as error:
        return _refused(error)
    return jsonify({"document": saved["document"], "version": saved["version"]}), 200


@v2_bp.route("/coaches/speaking-coach/preview", methods=["POST"])
@require_auth
def v2_coach_preview():
    blocked = _ring()
    if blocked:
        return blocked
    body = request.get_json(silent=True) or {}
    try:
        # preview() does not take the database.
        return jsonify(coach.preview(body.get("document"))), 200
    except coach.CoachRefused as error:
        return _refused(error)


@v2_bp.route("/coaches/speaking-coach/plugins", methods=["POST"])
@require_auth
def v2_coach_plugin():
    blocked = _ring()
    if blocked:
        return blocked
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(coach.keep_plugin(db, str(request.user_id), body.get("source"))), 200
    except Exception as error:  # noqa: BLE001 -- the check is the answer when the store cannot keep it
        logger.warning("coach plugin not stored: %s", type(error).__name__, exc_info=True)
        return jsonify(coach.check_plugin(body.get("source"))), 200


@v2_bp.route("/coaches/speaking-coach/publish", methods=["POST"])
@require_auth
@require_founder
def v2_coach_publish():
    blocked = _ring()
    if blocked:
        return blocked
    try:
        coach.publish(db, str(request.user_id))
    except coach.CoachRefused as error:
        return _refused(error)
    return jsonify({"published": True}), 200


@v2_bp.route("/coaches/speaking-coach/active", methods=["GET"])
@require_auth
def v2_coach_active():
    document = coach.read_active(db, str(request.user_id))
    return jsonify({"document": document}), 200
