"""The founder's voice notebook (Will learning plan, step 1; founder
2026-10-20). Service: services/voice_notebook.py.

  GET  /v2/notebook/state    {enabled, consented, max_seconds}
  POST /v2/notebook/ask      the question before the first note, in the thread
  POST /v2/notebook/consent  {choice: yes | not_now}
  POST /v2/notebook/notes    multipart: audio (≤ 5 min), duration_ms, key
  POST /v2/notebook/live     multipart: audio, a few seconds → {text} (N194)
  POST /v2/notebook/fix      {client_id, text}: a voice note's words fixed
  GET  /v2/notebook/sunday/<id>           the Sunday note's lens as it stands
  POST /v2/notebook/sunday/<id>/answer    {step, value}: one tap of the lens

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
from services.rate_limits import live_note_limit, llm_limit

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
        messages = decide(db, str(request.user_id), str(body.get("choice") or ""))
        if any((m.get("metadata") or {}).get("voice_note") for m in messages):
            messages += _goals_after_note(str(request.user_id))
        return jsonify({"messages": messages}), 200
    except NotebookError as e:
        return _error(e)
    except Exception as e:
        logger.error("notebook consent failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


@v2_bp.route("/notebook/sales-step", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_notebook_sales_step():
    """A tap on one of the sale's four steps (N241 P2): the step, then Will's
    one change to it."""
    from services.sales_framing import SalesError, answer
    body = request.get_json(silent=True) or {}
    try:
        messages = answer(db, str(request.user_id), body.get("note"), body.get("step"))
        return jsonify({"messages": messages}), 200
    except SalesError as e:
        return _error(e)
    except Exception as e:
        logger.error("sales step failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


def _goals_after_note(user_id: str) -> list:
    """Under a note's "Noted.", the ask for life goals (N172 M1), then the
    sales question or Will's answer to a worry (N241 O1, P2); never in the
    way of the note."""
    rows: list = []
    try:
        from services.life_goals import after_note
        rows += after_note(db, user_id)
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("life goals ask failed user=%s: %s", user_id, e)
    from services.sales_framing import answers_after_note
    rows += answers_after_note(db, user_id)
    try:
        from services.strengths import after_note as strengths_after_note
        rows += strengths_after_note(db, user_id)
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("strengths read failed user=%s: %s", user_id, e)
    return rows


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
            content_type=upload.mimetype or "audio/webm", duration_ms=duration,
            key=request.form.get("key"))
        return jsonify({"messages": messages + _goals_after_note(user_id)}), 200
    except NotebookError as e:
        return _error(e)
    except Exception as e:
        logger.error("voice note failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the note"}), 500


@v2_bp.route("/notebook/live", methods=["POST"])
@phase1_provider_route
@live_note_limit
@require_auth
def v2_notebook_live():
    """The words so far of a note being said (N194); nothing is kept."""
    from services.voice_notebook import NotebookError, enabled, preview
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    upload = request.files.get("audio")
    if upload is None:
        return jsonify({"code": "EMPTY_AUDIO", "error": "No audio."}), 400
    try:
        text = preview(db, user_id, _adapter(user_id), upload.read(),
                       filename=upload.filename or "piece.webm")
        return jsonify({"text": text}), 200
    except NotebookError as e:
        return _error(e)
    except Exception as e:
        logger.warning("live note piece failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR", "error": "Failed to hear the piece"}), 500


@v2_bp.route("/notebook/fix", methods=["POST"])
@require_auth
def v2_notebook_fix():
    """A voice note's words fixed by the person (N194)."""
    from services.voice_notebook import NotebookError, fix_note
    body = request.get_json(silent=True) or {}
    try:
        row = fix_note(db, str(request.user_id), str(body.get("client_id") or ""),
                       str(body.get("text") or ""))
        return jsonify({"messages": [row]}), 200
    except NotebookError as e:
        return _error(e)
    except Exception as e:
        logger.error("voice note fix failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the words"}), 500


def _sunday(work):
    from services.sunday_note import SundayError
    from services.voice_notebook import enabled
    user_id = str(request.user_id)
    if not enabled(db, user_id):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    try:
        return jsonify(work(user_id)), 200
    except SundayError as e:
        return _error(e)
    except Exception as e:
        logger.error("sunday note failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


@v2_bp.route("/notebook/sunday/<note_id>", methods=["GET"])
@require_auth
def v2_sunday_note_state(note_id):
    """The Sunday note's lens as it stands (N158 L3 to L8)."""
    from services.sunday_note import state
    return _sunday(lambda user_id: state(db, user_id, str(note_id)))


@v2_bp.route("/notebook/sunday/<note_id>/answer", methods=["POST"])
@require_auth
def v2_sunday_note_answer(note_id):
    """One tap of the lens, or Not now under the case: kept as rows of the
    one thread; answers with the lens as it stands."""
    from services.sunday_note import answer
    body = request.get_json(silent=True) or {}
    return _sunday(lambda user_id: answer(db, user_id, str(note_id),
                                          str(body.get("step") or ""), body.get("value")))
