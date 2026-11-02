"""The chats between people, first slice (founder 2026-10-31, N298 to N316;
the voice note, N321 item 2). Service: services/chats.py.

  GET  /v2/chats                  {chats: [{id, kind, title, subtitle,
                                   last: {kind, body, created_at} | null}]}
  GET  /v2/chats/<id>/messages    {messages: [{id, mine, author, kind, body,
                                   meta, created_at}]}, oldest first
  POST /v2/chats/<id>/messages    {kind: "emoji", body: "👍" | "👀" | "🙏"};
                                   {message: {...}}
  POST /v2/chats/<id>/voice       multipart: audio (the recording; its type is
                                   kept as it came, e.g. audio/webm;codecs=opus),
                                   duration_ms (1 to 120000); {message: {...,
                                   kind: "voice", body: "", meta: {duration_ms}}}
  GET  /v2/chats/<id>/messages/<message_id>/audio
                                   the recording, for any member of the chat
  POST /v2/chats/demo             makes the two demo chats once; the list

Ring row ``chats`` (ring 6): a person without it gets 404 from every route,
as a chat they are not in does. Anything but the three emoji is 400. No
provider call. A voice note is a speaker's recording, and ``/v2/chats`` is
outside the core gate's prefixes, so its upload passes the processing-
authorization path itself, after the ring and the chat (404) and before the
recording is looked at (400, 413): ``phase1_provider_route``, as the voice
notebook's notes, then the recording consent a Take asks for
(``require_current``, operation "recording", in every gate mode). A refusal
answers as those do, ``{code, error}`` with its status (403
PROCESSING_RECORDING_WITHDRAWN, 403 PROCESSING_AUTHORIZATION_REQUIRED, ...),
and nothing is written.
"""
import io
import logging
from functools import wraps

import sentry_sdk
from flask import jsonify, request, send_file

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.db import db

logger = logging.getLogger(__name__)


def _json(result):
    return jsonify(result), 200


def _run(label: str, work, answer=_json):
    """One answer for every route: the service's error as it is, anything
    else a 500 that is logged; otherwise ``answer`` of the result (by
    default the result as JSON), made outside the catch."""
    from services.chats import ChatsError
    try:
        result = work()
    except ChatsError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("chats %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to reach the chats"}), 500
    return answer(result)


@v2_bp.route("/chats", methods=["GET"])
@require_auth
def v2_chats_list():
    from services.chats import list_chats
    return _run("list", lambda: list_chats(db, str(request.user_id)))


@v2_bp.route("/chats/<thread_id>/messages", methods=["GET"])
@require_auth
def v2_chats_read(thread_id):
    from services.chats import read
    return _run("read", lambda: read(db, str(request.user_id), thread_id))


@v2_bp.route("/chats/<thread_id>/messages", methods=["POST"])
@require_auth
def v2_chats_post(thread_id):
    from services.chats import post
    body = request.get_json(silent=True)
    return _run("post", lambda: post(db, str(request.user_id), thread_id, body))


def _a_member_first(view):
    """A voice note's first check, before its processing authorization: the
    ring and the chat, else 404, as every route here answers."""
    @wraps(view)
    def wrapped(thread_id):
        from services.chats import member
        return _run("voice", lambda: member(db, str(request.user_id), thread_id),
                    answer=lambda _membership: view(thread_id))
    return wrapped


def _recording_refused():
    """The recording consent a Take asks for (routes/v2/lab_recording.py),
    asked of the caller's acquisition principal, resolved as
    ``phase1_provider_route`` resolves it. In every gate mode: a withdrawn
    consent is honoured whether or not the gate is on. None, or the refusal
    as the processing-authorization routes answer it. Anything unexpected
    goes to the app's JSON error net, as in ``phase1_provider_route``."""
    from routes.v2.processing_authorization import _principal_error, _principal_id
    from services.create_take import CreateTakeError
    from services.processing_authorization import (
        ProcessingAuthorizationError, ProcessingAuthorizationService,
    )
    from services.project_repository import ProjectOwnershipError
    try:
        ProcessingAuthorizationService(db).require_current(
            _principal_id(), operation="recording")
    except (CreateTakeError, ProjectOwnershipError) as error:
        return _principal_error(error)
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    return None


@v2_bp.route("/chats/<thread_id>/voice", methods=["POST"])
@require_auth
@_a_member_first
@phase1_provider_route
def v2_chats_voice(thread_id):
    """A voice note. Its checks in order: the ring and the chat (404); the
    caller's processing authorization (``phase1_provider_route``) and
    recording consent (their refusal); the recording (400, 413). Then its
    message and its recording are written."""
    refused = _recording_refused()
    if refused is not None:
        return refused
    from services.chats import MAX_VOICE_BYTES, post_voice
    upload = request.files.get("audio")
    # One byte past the limit is enough to know it is over (413).
    audio = upload.stream.read(MAX_VOICE_BYTES + 1) if upload is not None else b""
    content_type = upload.content_type if upload is not None else None
    return _run("voice", lambda: post_voice(
        db, str(request.user_id), thread_id, audio, content_type=content_type,
        duration_ms=request.form.get("duration_ms")))


@v2_bp.route("/chats/<thread_id>/messages/<message_id>/audio", methods=["GET"])
@require_auth
def v2_chats_audio(thread_id, message_id):
    """A voice note's recording, for any member of its chat; byte ranges
    answered, as an audio element asks for them."""
    from services.chats import recording

    def played(got):
        response = send_file(io.BytesIO(got["audio"]), mimetype=got["content_type"],
                             conditional=True)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response
    return _run("audio", lambda: recording(db, str(request.user_id), thread_id, message_id),
                answer=played)


@v2_bp.route("/chats/demo", methods=["POST"])
@require_auth
def v2_chats_demo():
    from services.chats import seed_demo
    return _run("demo", lambda: seed_demo(db, str(request.user_id)))
