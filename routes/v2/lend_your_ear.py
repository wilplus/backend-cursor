"""Phase 4 of the after-practice paths (founder 2026-10-01, F3, F4): the
share toggle on a Voice Album moment, Lend your ear, and the licensed
corpus the coaches keep. Every route answers 404 while ``PEER_LANE_ENABLED``
is off (it stays off until counsel answers C1 to C3). The work is
``services.lend_your_ear``' and ``services.corpus_clips``'.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from config import Config
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


@v2_bp.route("/user/voice-album/<snippet_id>/share", methods=["PUT"])
@require_auth
def v2_voice_album_share(snippet_id):
    """Body {shared: true | false}: lend this Voice Album moment to other
    speakers' ears, or take it back; a withdrawal leaves both pools at once."""
    from services.lend_your_ear import set_share
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    return _run("voice-album share", lambda: set_share(
        db, owner_user_id=str(request.user_id), snippet_id=snippet_id,
        body=request.get_json(silent=True)))


@v2_bp.route("/user/takes/<take_session_id>/lend-your-ear", methods=["GET"])
@require_auth
def v2_lend_your_ear(take_session_id):
    """The Take's set of up to three clips, audio only, built once after a
    practice that lands; 409 NOT_YET before one."""
    from services.lend_your_ear import open_set
    if not _is_valid_uuid(take_session_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "take_session_id must be a valid UUID"}), 400
    return _run("lend-your-ear", lambda: open_set(
        db, listener_id=str(request.user_id), take_session_id=take_session_id))


@v2_bp.route("/user/lend-your-ear/<set_id>/answers", methods=["POST"])
@require_auth
def v2_lend_your_ear_answer(set_id):
    """Body {clip_id, value}: one of the five answers on one clip of the
    set, once per person per clip."""
    from services.lend_your_ear import answer
    if not _is_valid_uuid(set_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "set_id must be a valid UUID"}), 400
    return _run("lend-your-ear answer", lambda: answer(
        db, listener_id=str(request.user_id), set_id=set_id,
        body=request.get_json(silent=True)))


@v2_bp.route("/coach/licensed-clips", methods=["GET"])
@require_admin_or_coach
def v2_corpus_clips():
    """The licensed corpus, for the coaches who keep it."""
    from services.corpus_clips import list_clips
    return _run("corpus clips list", lambda: list_clips(db))


@v2_bp.route("/coach/licensed-clips", methods=["POST"])
@require_admin_or_coach
def v2_corpus_clip_create():
    """multipart/form-data: licence (who licensed it, under what), passage,
    media_file (audio). 201 {clip} · 400/413/415/502/503."""
    from services.corpus_clips import create_clip
    return _run("corpus clip create", lambda: create_clip(
        db, coach_id=str(request.user_id), licence=request.form.get("licence"),
        passage=request.form.get("passage"), media_file=request.files.get("media_file"),
        max_mb=int(getattr(Config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100) or 100)))


@v2_bp.route("/coach/licensed-clips/<clip_id>/label", methods=["PUT"])
@require_admin_or_coach
def v2_corpus_clip_label(clip_id):
    """Body {value: "yes" | "no" | null}: the coach's own read of a licensed
    clip; a Yes lets it into Bold voices (F4)."""
    from services.corpus_clips import label_clip
    if not _is_valid_uuid(clip_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "clip_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}
    return _run("corpus clip label", lambda: label_clip(
        db, coach_id=str(request.user_id), clip_id=clip_id, value=body.get("value")))
