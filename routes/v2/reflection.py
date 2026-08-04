"""The Reflection Game surface: /v2/reflection/*, the coach verdict queue
and the confident-voices library read.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 5);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.admin import require_admin_or_coach
from routes.v2.common import _resolve_snippet_audio_url
from config import Config
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


def _reflection_audio_map(clips):
    """clip rows → {clip_id: resolved audio url}. One bulk snippet read;
    a clip whose audio cannot be resolved is unplayable and is dropped
    by the caller rather than served dead."""
    ids = [str(c.get("snippet_id")) for c in clips if c.get("snippet_id")]
    if not ids:
        return {}
    snips = {str(s.get("id")): s
             for s in (db.get_snippets_by_ids(ids) or [])}
    out = {}
    for c in clips:
        s = snips.get(str(c.get("snippet_id")))
        if not s:
            continue
        try:
            url = _resolve_snippet_audio_url(s)
        except Exception:
            url = s.get("audio_segment_path")
        if url:
            out[str(c.get("id"))] = url
    return out


@v2_bp.route("/reflection/clips", methods=["GET"])
@require_auth
def v2_reflection_get_clips():
    """Up to 2 pending clips for the signed-in user (server-side cadence
    authority). Payload per clip — EXACTLY these keys, nothing that
    distinguishes a flagged clip from a decoy, no confidence of any
    kind (the network tab is a user surface):

    200 { clips: [{ clip_id, audio_ref, start_offset_ms, duration_ms,
                    arc_id, take_session_id }] }
    """
    try:
        from services.reflection_game import serve_clips
        rows = serve_clips(str(request.user_id))
        audio = _reflection_audio_map(rows)
        clips = []
        for c in rows:
            _aid = str(c.get("id"))
            if _aid not in audio:
                continue
            clips.append({
                "clip_id": _aid,
                "audio_ref": audio[_aid],
                "start_offset_ms": c.get("start_offset_ms"),
                "duration_ms": c.get("duration_ms"),
                "arc_id": c.get("arc_id"),
                "take_session_id": c.get("take_session_id"),
            })
        return jsonify({"clips": clips}), 200
    except Exception as e:
        logger.error("reflection clips GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load clips"}), 500


@v2_bp.route("/reflection/clips/<clip_id>/vote", methods=["POST"])
@require_auth
def v2_reflection_vote(clip_id):
    """The user's answer to "How did this moment land for you?".
    Body: { vote: "best" | "not_this" }. Recorded regardless of decoy
    status; a re-vote OVERWRITES (idempotent — FE handles either).
    200 { saved: true } · 400 · 404 · 500
    """
    try:
        body = request.get_json(silent=True) or {}
        vote = body.get("vote")
        if vote not in ("best", "not_this"):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "vote must be best or not_this"}), 400
        row = db.set_reflection_vote(str(clip_id), str(request.user_id),
                                     vote)
        if not row:
            return jsonify({"code": "NOT_FOUND",
                            "error": "clip not found"}), 404
        return jsonify({"saved": True}), 200
    except Exception as e:
        logger.error("reflection vote failed clip=%s: %s", clip_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the vote"}), 500


@v2_bp.route("/coach/reflection/queue", methods=["GET"])
@require_admin_or_coach
def v2_coach_reflection_queue():
    """Voted clips awaiting the coach's BLIND verdict, oldest vote
    first. AUDIO + TRANSCRIPT ONLY (BLIND COACH fence): no machine
    flag, no provenance, no confidence, no user vote — the agreement
    matrix is computed off-surface and never shown. Queue PRIORITY
    (founder decision): text verification outranks these — the coach
    surface lists this queue BELOW text-verification work.

    200 { clips: [{ clip_id, audio_ref, start_offset_ms, duration_ms,
                    transcript }] }
    """
    try:
        rows = db.list_reflection_clips_for_coach(limit=20)
        audio = _reflection_audio_map(rows)
        clips = []
        for c in rows:
            _aid = str(c.get("id"))
            if _aid not in audio:
                continue
            clips.append({
                "clip_id": _aid,
                "audio_ref": audio[_aid],
                "start_offset_ms": c.get("start_offset_ms"),
                "duration_ms": c.get("duration_ms"),
                "transcript": c.get("transcript") or "",
            })
        return jsonify({"clips": clips}), 200
    except Exception as e:
        logger.error("coach reflection queue failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load the queue"}), 500


@v2_bp.route("/coach/reflection/<clip_id>/verdict", methods=["POST"])
@require_admin_or_coach
def v2_coach_reflection_verdict(clip_id):
    """The coach's blind verdict. Body: { verdict: "confident" |
    "not_confident" }. 'confident' lands the moment in the user's
    cross-project Confident Voices library — DECOYS INCLUDED (a coach-
    verified decoy is a coach-verified confident moment, and a logged
    false-negative for the model). Completes the matrix row (internal
    log only). 200 { saved: true } · 400 · 404 · 500
    """
    try:
        body = request.get_json(silent=True) or {}
        verdict = body.get("verdict")
        if verdict not in ("confident", "not_confident"):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "verdict must be confident or not_confident",
            }), 400
        row = db.set_reflection_verdict(str(clip_id), verdict)
        if not row:
            return jsonify({"code": "NOT_FOUND",
                            "error": "clip not found"}), 404
        # §1f — the three-way agreement matrix, off-surface. This log
        # line is the F2 label stream; nothing here reaches a payload.
        from services.reflection_game import log_matrix_row
        log_matrix_row(row)
        return jsonify({"saved": True}), 200
    except Exception as e:
        logger.error("reflection verdict failed clip=%s: %s", clip_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the verdict"}), 500


@v2_bp.route("/library/confident-voices", methods=["GET"])
@require_auth
def v2_library_confident_voices():
    """The user's Confident Voices library — CROSS-PROJECT (global per
    user, founder decision), coach-verified moments only, newest first.
    AC-9 standing rule: no counts, no streaks, no "N verified"
    aggregates — a list is a list.

    200 { items: [{ id, audio_ref, start_offset_ms, duration_ms,
                    arc_id, topic, verified_at }] }
    """
    try:
        rows = db.list_confident_voices(str(request.user_id))
        audio = _reflection_audio_map(rows)
        items = []
        for c in rows:
            _aid = str(c.get("id"))
            if _aid not in audio:
                continue
            items.append({
                "id": _aid,
                "audio_ref": audio[_aid],
                "start_offset_ms": c.get("start_offset_ms"),
                "duration_ms": c.get("duration_ms"),
                "arc_id": c.get("arc_id"),
                "topic": c.get("topic"),
                "verified_at": c.get("verified_at"),
            })
        return jsonify({"items": items}), 200
    except Exception as e:
        logger.error("confident-voices GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load the library"}), 500
