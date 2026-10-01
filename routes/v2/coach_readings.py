"""The coach's model readings (founder 2026-10-01; Phase 3 of the
after-practice paths; migration 0409): record, list, publish. Published
readings play to speakers in Bold voices without the coach's name; the coach
agreement covers that use. Every route answers 404 while
``PRAISE_AFTER_PRACTICE_ENABLED`` is off. The work is
``services.coach_readings``'.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

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


@v2_bp.route("/coach/readings", methods=["GET"])
@require_admin_or_coach
def v2_coach_readings():
    """This coach's own readings, published or not."""
    from services.coach_readings import list_readings
    return _run("coach readings list", lambda: list_readings(
        db, coach_id=str(request.user_id)))


@v2_bp.route("/coach/readings", methods=["POST"])
@require_admin_or_coach
def v2_coach_reading_create():
    """multipart/form-data: passage, media_kind (audio | video), media_file.
    201 {reading} · 400/413/415/502/503."""
    from services.coach_readings import create_reading
    return _run("coach reading create", lambda: create_reading(
        db, coach_id=str(request.user_id), passage=request.form.get("passage"),
        media_kind=request.form.get("media_kind") or "audio",
        media_file=request.files.get("media_file"),
        max_mb=int(getattr(Config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100) or 100)))


@v2_bp.route("/coach/readings/<reading_id>/publish", methods=["POST"])
@require_admin_or_coach
def v2_coach_reading_publish(reading_id):
    """Body {published: true | false}: publish or withdraw one's own reading."""
    from services.coach_readings import publish_reading
    if not _is_valid_uuid(reading_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "reading_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}
    return _run("coach reading publish", lambda: publish_reading(
        db, coach_id=str(request.user_id), reading_id=reading_id,
        published=body.get("published")))
