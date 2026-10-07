"""Exercise authoring inside the coach panel (founder 2026-09-29, decision 4;
build-order item 1).

The coach files and edits exercises here with the same catalogue service and
the same live library the CMS uses (services/diagnostic_exercise_catalogue),
so the two places cannot drift. Every save keeps its version (0399). The
video is transcribed at upload through the authorized provider path under
the coach's own processing authorization (services/exercise_versions). The
AI script draft is a candidate the coach edits; it is returned to the coach
and stored only beside the coach's final when they save, never served.
The founder retires an exercise or brings it back at
PUT /admin/exercises/<exercise_id>/active (coach panel lock CP3 A).

Thin on purpose (route fence): validate, authorise, one service call,
serialise. Coach or admin only; nothing here is a speaker route.
"""
from __future__ import annotations

import json
import logging
import os

from flask import jsonify, request
from werkzeug.utils import secure_filename

from config import Config
from routes.admin import require_admin_or_coach, require_founder
from routes.v2.blueprint import v2_bp
from services.db import db
from services.rate_limits import heavy_limit, llm_limit

logger = logging.getLogger(__name__)
config = Config()

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


@v2_bp.route("/coach/exercises", methods=["GET"])
@require_admin_or_coach
def v2_coach_list_exercises():
    """The library as the coach authors it: every exercise with its targets
    and its latest version, and the speaking-error library for the pickers.
    200 { exercises, speaking_errors }"""
    from services.coach_exercise_authoring import library_for_authoring
    return jsonify(library_for_authoring(db)), 200


@v2_bp.route("/coach/exercises", methods=["POST"])
@require_admin_or_coach
def v2_coach_save_exercise():
    """Create or update one exercise, with the CMS's own refusals.
    Body: the catalogue fields, plus optional ai_draft_text and
    ai_draft_model_version (kept beside the final on the version row).
    200 { exercise, version } · 400 (a refusal, readable) · 500"""
    from services.coach_exercise_authoring import save_from_coach_panel
    from services.diagnostic_exercise_catalogue import CatalogueRefusal
    try:
        saved = save_from_coach_panel(
            db, request.get_json(silent=True) or {},
            coach_id=str(request.user_id))
    except CatalogueRefusal as refusal:
        return jsonify({"code": refusal.code, "error": refusal.message}), \
            refusal.status
    if not saved:
        return jsonify({"code": "V2_ERROR",
                        "error": "The exercise could not be saved."}), 500
    return jsonify(saved), 200


@v2_bp.route("/coach/exercises/<exercise_id>/video", methods=["POST"])
@heavy_limit
@require_admin_or_coach
def v2_coach_exercise_video(exercise_id):
    """The exercise's video: stored, hashed, transcribed at upload.
    multipart/form-data: video_file (.mp4/.mov/.webm/.m4v); exercise (JSON,
    optional): the definition -- required for a NEW exercise, since the
    library refuses one without a video, and an edit for an existing one.
    200 { exercise, version, transcript_status } · 400 · 404 · 413 · 415 · 502"""
    from services.coach_exercise_authoring import attach_video
    definition = None
    if (request.form.get("exercise") or "").strip():
        try:
            definition = json.loads(request.form["exercise"])
        except ValueError:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "exercise must be JSON"}), 400
    max_mb = max(1, int(getattr(config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100)))
    if (request.content_length or 0) > max_mb * 1024 * 1024:
        return jsonify({"code": "PAYLOAD_TOO_LARGE",
                        "error": f"Video is too large. Max allowed is {max_mb}MB."}), 413
    video_file = request.files.get("video_file")
    if video_file is None or not (video_file.filename or "").strip():
        return jsonify({"code": "INVALID_INPUT", "error": "video_file is required"}), 400
    safe_name = secure_filename(video_file.filename or "")
    if os.path.splitext(safe_name)[1].lower() not in _VIDEO_EXTENSIONS:
        return jsonify({"code": "INVALID_VIDEO_FORMAT",
                        "error": "Supported formats: .mp4, .mov, .webm, .m4v"}), 415
    video_bytes = video_file.read() or b""
    if not video_bytes:
        return jsonify({"code": "INVALID_INPUT", "error": "video_file is empty"}), 400
    if len(video_bytes) > max_mb * 1024 * 1024:
        return jsonify({"code": "PAYLOAD_TOO_LARGE",
                        "error": f"Video is too large. Max allowed is {max_mb}MB."}), 413
    status, payload = attach_video(
        db, exercise_id=str(exercise_id), coach_id=str(request.user_id),
        video_bytes=video_bytes, filename=safe_name,
        content_type=video_file.content_type or "video/mp4",
        definition=definition)
    return jsonify(payload), status


@v2_bp.route("/coach/exercises/script-draft", methods=["POST"])
@llm_limit
@require_admin_or_coach
def v2_coach_exercise_script_draft():
    """A first script for the coach's video, from the library's own past
    finals for the named errors. Returned to the coach only; nothing is
    stored until they save. Body { error_ids: [..], title?, notes? }.
    200 { draft, model_version } · 400 · 503"""
    from services.coach_exercise_authoring import draft_script
    status, payload = draft_script(
        db, request.get_json(silent=True) or {}, coach_id=str(request.user_id))
    return jsonify(payload), status


@v2_bp.route("/admin/exercises/<exercise_id>/active", methods=["PUT"])
@require_founder
def v2_admin_exercise_active(exercise_id):
    """Retire an exercise from the library, or bring it back (coach panel
    lock CP3 A, the founder's Library page). Body {active: bool}. A retired
    exercise is never matched or offered. Founder only.
    200 {exercise_id, active, changed} · 400 · 403 · 404 · 409 · 500"""
    from services.exercise_retirement import set_exercise_active
    status, payload = set_exercise_active(
        db, str(exercise_id), request.get_json(silent=True))
    return jsonify(payload), status
