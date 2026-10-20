"""The founder's voice notebook (Will learning plan, step 1; founder
2026-10-20). Service: services/voice_notebook.py.

  GET  /v2/notebook/state    {enabled, consented, max_seconds}
  POST /v2/notebook/ask      the question before the first note, in the thread
  POST /v2/notebook/consent  {choice: yes | not_now}
  POST /v2/notebook/notes    multipart: audio (≤ 5 min), duration_ms
  POST /v2/notebook/sunday/<id>/pattern    {choice: old | new}
  POST /v2/notebook/sunday/<id>/principle  {choice: add | not_now}

GET state takes ?tz=<IANA zone> (the browser's): kept for whoever said Yes,
so the Sunday note (services/sunday_note.py) comes at 6 pm their time.

A person without the notebook gets enabled false from state and 404 from
the rest. The recording's transcription runs under the caller's
processing authorization (``phase1_provider_route``), like the chat.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.db import db
from services.rate_limits import llm_limit

logger = logging.getLogger(__name__)


def _error(e):
    return jsonify({"code": e.code, "error": str(e)}), e.status


@v2_bp.route("/notebook/state", methods=["GET"])
@require_auth
def v2_notebook_state():
    from services.sunday_note import valid_zone
    from services.voice_notebook import state
    now = state(db, str(request.user_id))
    zone = request.args.get("tz")
    if now["consented"] and valid_zone(zone):
        db.set_voice_notebook_time_zone(str(request.user_id), str(zone))
    return jsonify(now), 200


@v2_bp.route("/notebook/ask", methods=["POST"])
@require_auth
def v2_notebook_ask():
    from services.voice_notebook import ask_rows, enabled
    if not enabled(db, str(request.user_id)):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    return jsonify({"messages": ask_rows(db, str(request.user_id))}), 200


@v2_bp.route("/notebook/consent", methods=["POST"])
@require_auth
def v2_notebook_consent():
    from services.voice_notebook import NotebookError, decide
    body = request.get_json(silent=True) or {}
    try:
        return jsonify({"messages": decide(db, str(request.user_id),
                                           str(body.get("choice") or ""))}), 200
    except NotebookError as e:
        return _error(e)
    except Exception as e:
        logger.error("notebook consent failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


def _adapter(user_id: str):
    """The request's authorized adapter; outside enforcement, one with the
    person's principal (its permits are then no-ops, as everywhere)."""
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, scoped_adapter,
    )
    from services.rings import principal_for_user
    return scoped_adapter() or AuthorizedProviderAdapter(
        db, ProviderCoordinates(principal_for_user(user_id) or "", None, None))


@v2_bp.route("/notebook/notes", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_notebook_note():
    from services.voice_notebook import NotebookError, add_voice_note, enabled
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    upload = request.files.get("audio")
    if upload is None:
        return jsonify({"code": "EMPTY_AUDIO", "error": "No audio."}), 400
    try:
        duration = int(request.form.get("duration_ms") or 0) or None
    except ValueError:
        duration = None
    try:
        messages = add_voice_note(
            db, user_id, _adapter(user_id), upload.read(),
            filename=upload.filename or "note.webm",
            content_type=upload.mimetype or "audio/webm", duration_ms=duration)
        return jsonify({"messages": messages}), 200
    except NotebookError as e:
        return _error(e)
    except Exception as e:
        logger.error("voice note failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the note"}), 500


def _sunday(answer, note_id):
    from services.sunday_note import SundayError
    from services.voice_notebook import enabled
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    body = request.get_json(silent=True) or {}
    try:
        return jsonify({"messages": answer(db, user_id, str(note_id),
                                           str(body.get("choice") or ""))}), 200
    except SundayError as e:
        return _error(e)
    except Exception as e:
        logger.error("sunday note answer failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


@v2_bp.route("/notebook/sunday/<note_id>/pattern", methods=["POST"])
@require_auth
def v2_sunday_note_pattern(note_id):
    """Old or New for the week's bug (Will learning plan, step 2)."""
    from services.sunday_note import mark
    return _sunday(mark, note_id)


@v2_bp.route("/notebook/sunday/<note_id>/principle", methods=["POST"])
@require_auth
def v2_sunday_note_principle(note_id):
    """Add principle (to the Life Panel's active principles) or Not now."""
    from services.sunday_note import principle
    return _sunday(principle, note_id)
