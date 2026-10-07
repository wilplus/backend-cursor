"""The retired share switch and per-Take Lend your ear set (404
tombstones), and the licensed corpus the coaches keep.

Founder 2026-10-07, Q-B11 A (decisions log N62): "Lend your ear's engine
serves them [the walk's other voices] under the per-Take consent only. The
Album share switch and Bold voices are retired." The Voice Album share
switch and the per-Take set it fed are gone: the three speaker routes
below stay registered so the URL map keeps its shape and answer 404
whatever ``PEER_LANE_ENABLED`` says, before any read or write. The walk's
other voices are served by ``GET /v2/user/communities/queue``
(``services/lend_your_ear.other_voices`` under ``services/communities``).
The ``voice_album_shares``, ``lend_your_ear_sets`` and
``lend_your_ear_answers`` tables are not dropped.

The coach's licensed-corpus tool (``services/corpus_clips.py``) stays,
still behind ``PEER_LANE_ENABLED``: its clips are the walk's training
clips.
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


def _retired():
    """Every call: 404, nothing read, nothing written."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/user/voice-album/<snippet_id>/share", methods=["PUT"])
@require_auth
def v2_voice_album_share(snippet_id):
    """The Album share switch: retired (Q-B11 A), 404."""
    return _retired()


@v2_bp.route("/user/takes/<take_session_id>/lend-your-ear", methods=["GET"])
@require_auth
def v2_lend_your_ear(take_session_id):
    """The per-Take blind set the share switch fed: retired (Q-B11 A), 404."""
    return _retired()


@v2_bp.route("/user/lend-your-ear/<set_id>/answers", methods=["POST"])
@require_auth
def v2_lend_your_ear_answer(set_id):
    """An answer on the retired set: retired (Q-B11 A), 404."""
    return _retired()


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
    clip, kept on the row (Bold voices, which a Yes once opened, is retired)."""
    from services.corpus_clips import label_clip
    if not _is_valid_uuid(clip_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "clip_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}
    return _run("corpus clip label", lambda: label_clip(
        db, coach_id=str(request.user_id), clip_id=clip_id, value=body.get("value")))
