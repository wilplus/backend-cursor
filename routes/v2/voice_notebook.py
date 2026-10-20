"""The founder's voice notebook (Will learning plan, step 1; founder
2026-10-20). Service: services/voice_notebook.py.

  GET  /v2/notebook/state    {enabled, consented, max_seconds}
  POST /v2/notebook/ask      the question before the first note, in the thread
  POST /v2/notebook/consent  {choice: yes | not_now}
  POST /v2/notebook/notes    multipart: audio (≤ 5 min), duration_ms

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

logger = logging.getLogger(__name__)


def _error(e):
    return jsonify({"code": e.code, "error": str(e)}), e.status


@v2_bp.route("/notebook/state", methods=["GET"])
@require_auth
def v2_notebook_state():
    from services.voice_notebook import state
    return jsonify(state(db, str(request.user_id))), 200


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
