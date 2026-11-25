"""The AI version of your voice: the walk's clip and the Data & consent card
(founder lock 2026-10-12, docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md).

  POST /v2/user/confidence-practice/<id>/ai-voice        enter the lane: start
                                                         the clip (once) and
                                                         return its state
  GET  /v2/user/confidence-practice/<id>/ai-voice        the clip's state
  POST /v2/user/confidence-practice/<id>/ai-voice/play   one play
  POST /v2/user/lounge/moment/<snippet_id>/ai-voice     example in the chat
  GET/POST/DELETE /v2/user/ai-voice                      the card: state,
                                                         Turn on, Delete

Responses carry codes, states and a short-lived link, and with a ready
clip its one signed sentence on what changed and why (WIL-82); every other
word on screen is the frontend's, signed by the founder. No provider id,
setting, score or check result is returned. The logic lives in
services.ai_voice_*.
"""
from __future__ import annotations

import logging
from io import BytesIO

import sentry_sdk
from flask import jsonify, request, send_file

from auth import require_auth
from routes.phase2_guard import consent_choice_required, operational_purpose_disabled
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from services import ai_voice_clip, ai_voice_clone
from services.db import db
from services.refusal import Refusal

logger = logging.getLogger(__name__)


def _owned_practice(practice_id: str):
    if not _is_valid_uuid(practice_id):
        return None, (jsonify({"code": "INVALID_INPUT"}), 400)
    practice = db.get_confident_voice_practice(practice_id, str(getattr(request, "user_id", "")))
    if not practice:
        return None, (jsonify({"code": "NOT_FOUND"}), 404)
    return practice, None


def _chat_retry_available(practice: dict, retry: str, user: str) -> bool:
    return _is_valid_uuid(retry) and bool(ai_voice_clip.chat_retry_evidence(db, practice, user, retry))


@v2_bp.route("/user/confidence-practice/<practice_id>/ai-voice/chat/<chat_retry_id>", methods=["GET"])
@v2_bp.route("/user/confidence-practice/<practice_id>/ai-voice", methods=["GET", "POST"])
@require_auth
@operational_purpose_disabled("personalized_exercise_recommendation")
@consent_choice_required("personalised_practice")
def v2_practice_ai_voice(practice_id, chat_retry_id=None):
    practice, refused = _owned_practice(practice_id)
    if refused:
        return refused
    try:
        user_id = str(getattr(request, "user_id", ""))
        if request.method != "POST":
            from services.ai_voice_store import get_cycle
            if chat_retry_id:
                if not _chat_retry_available(practice, chat_retry_id, user_id):
                    return jsonify({"code": "NOT_FOUND"}), 404
                cycle = get_cycle(db, practice_id, chat_retry_id=chat_retry_id)
                response = jsonify(ai_voice_clip.state(db, practice, cycle))
                response.headers["Cache-Control"] = "private, no-store"
                return response, 200
            ai_voice_clip.note_attempts(
                db, practice, db.list_confident_voice_practice_attempts(practice_id) or [])
            return jsonify(ai_voice_clip.state(db, practice, get_cycle(db, practice_id))), 200
        principal = ai_voice_clip.principal_for(db, practice.get("take_session_id"), user_id)
        return jsonify(ai_voice_clip.ensure(
            db, practice, user_id=user_id, principal_id=principal)), 200
    except Exception as error:  # noqa: BLE001 — the walk goes on without a clip
        logger.error("ai voice: practice route failed: %s", type(error).__name__)
        sentry_sdk.capture_exception(error)
        return jsonify({"demo": "video" if ai_voice_clip._has_video(practice) else "none",
                        "clip": None}), 200


@v2_bp.route("/user/confidence-practice/<practice_id>/ai-voice/chat/<chat_retry_id>/audio", methods=["GET"])
@require_auth
@operational_purpose_disabled("personalized_exercise_recommendation")
@consent_choice_required("personalised_practice")
def v2_chat_retry_ai_audio(practice_id, chat_retry_id):
    from services.ai_voice_store import read_chat_audio

    practice, refused = _owned_practice(practice_id)
    if refused:
        return refused
    if not _chat_retry_available(practice, chat_retry_id, str(request.user_id)):
        return jsonify({"code": "NOT_FOUND"}), 404
    audio = read_chat_audio(db, practice_id, chat_retry_id)
    if not audio:
        return jsonify({"code": "NOT_FOUND"}), 404
    response = send_file(BytesIO(audio), mimetype="audio/mpeg", conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/user/lounge/moment/<snippet_id>/ai-voice", methods=["POST"])
@require_auth
@operational_purpose_disabled("personalized_exercise_recommendation")
@consent_choice_required("personalised_practice")
def v2_chat_moment_ai_voice(snippet_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"code": "INVALID_INPUT"}), 400
    arc_id, take_id = body.get("arc_id"), body.get("take_session_id")
    if not all(isinstance(value, str) and _is_valid_uuid(value) for value in (arc_id, take_id, snippet_id)):
        return jsonify({"code": "INVALID_INPUT"}), 400
    try:
        variant = {}
        if reply := body.get("coach_reply_id"):
            from services.chat_practice import opening_retry_id
            retry = opening_retry_id(db, str(request.user_id), reply, arc_id, take_id, snippet_id) if _is_valid_uuid(reply) else None
            if not retry:
                return jsonify({"code": "NOT_FOUND"}), 404
            variant["chat_retry_id"] = retry
        result = ai_voice_clip.prepare_chat_example(
            db, arc_id=arc_id, take_id=take_id, snippet_id=snippet_id,
            user_id=str(request.user_id), **variant,
        )
    except Refusal as error:
        return jsonify(error.body), error.status
    except Exception as error:  # noqa: BLE001 — keep the original clip playable in chat
        logger.warning("AI voice example unavailable in chat", exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "AI_VOICE_FAILED"}), 503
    response = jsonify(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/user/confidence-practice/<practice_id>/ai-voice/play", methods=["POST"])
@require_auth
@operational_purpose_disabled("personalized_exercise_recommendation")
@consent_choice_required("personalised_practice")
def v2_practice_ai_voice_play(practice_id):
    practice, refused = _owned_practice(practice_id)
    if refused:
        return refused
    ai_voice_clip.note_play(db, practice_id)
    return jsonify({"ok": True}), 200


@v2_bp.route("/user/ai-voice", methods=["GET", "POST", "DELETE"])
@require_auth
def v2_user_ai_voice():
    user_id = str(getattr(request, "user_id", ""))
    if not ai_voice_clone.available_to(user_id):
        return jsonify({"available": False}), 200
    try:
        if request.method == "POST":
            ai_voice_clone.turn_on(db, user_id)
        elif request.method == "DELETE":
            from services.ai_voice_store import get_clone
            source = (get_clone(db, user_id) or {}).get("source_take_id")
            result = ai_voice_clone.delete(
                db, user_id, principal_id=ai_voice_clip.principal_for(db, source, user_id))
            if result.get("state") == "deleting":
                return jsonify({"available": True, "state": "deleting",
                                "code": "DELETE_NOT_FINISHED"}), 202
        return jsonify(ai_voice_clone.card_state(db, user_id)), 200
    except Exception as error:  # noqa: BLE001
        logger.error("ai voice: card route failed: %s", type(error).__name__)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "AI_VOICE_FAILED"}), 500
