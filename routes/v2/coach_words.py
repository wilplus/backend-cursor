"""Drafts for the coach's own words (founder 2026-10-01, C5-a; Phase 7 of
the coach panel; migration 0411): the Take word, after every moment of the
Take is judged, and the personal line on a moment, after the moment's blind
rating. The draft is text from the transcript and the coach's notes; the
coach edits every word, and the pair is recorded on save by the services
the save already runs through. 404 while ``COACH_WORD_PAIRS_ENABLED`` is
off. The work is ``services.coach_word_pairs``'.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
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


@v2_bp.route("/coach/sessions/<session_id>/word/draft", methods=["POST"])
@require_admin_or_coach
def v2_coach_take_word_draft(session_id):
    """Body {notes?}: a draft of the Take word, kept on the coach's row."""
    from services.coach_word_pairs import draft_take_word
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    if not db.v2_get_session_by_id(session_id):
        return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
    return _run("take word draft", lambda: draft_take_word(
        db, take_session_id=str(session_id),
        coach_id=str(getattr(request, "user_id", "") or ""),
        body=request.get_json(silent=True)))


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/moment-line/draft",
    methods=["POST"],
)
@require_admin_or_coach
def v2_coach_moment_line_draft(session_id, snippet_id):
    """Body {notes?}: a draft of the personal line on this moment, behind
    the blind gate, kept on the moment's request row."""
    from routes.v2.coach import _moment_gate
    from services.coach_word_pairs import draft_moment_line
    error, owner_sid = _moment_gate(session_id, snippet_id)
    if error:
        return error
    return _run("moment line draft", lambda: draft_moment_line(
        db, request_row=db.get_exercise_coach_request(owner_sid, str(snippet_id)),
        coach_id=str(getattr(request, "user_id", "") or ""),
        body=request.get_json(silent=True)))
