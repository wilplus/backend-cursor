"""The chats between people, first slice (founder 2026-10-31, N298 to N316;
the voice note, N321 item 2; the photos and files of the "+", N351).
Service: services/chats.py.

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
  POST /v2/chats/<id>/photo       multipart: file (a jpeg, png, gif, webp,
                                   heic, heif or avif image, up to 10 MB);
                                   {message: {..., kind: "photo", body: "",
                                   meta: {question: true}}}
  POST /v2/chats/<id>/file        multipart: file (any type, up to 10 MB);
                                   {message: {..., kind: "file", body: its own
                                   name, meta: {question: true}}}
  GET  /v2/chats/<id>/messages/<message_id>/file
                                   the photo (inline) or the file (attachment),
                                   with its own name, for any member of the chat
  POST /v2/chats/demo             makes the two demo chats once; the list
  GET  /v2/chats/link             {token, path}: the caller's own join link,
                                   made the first time (N308)
  POST /v2/chats/link             the link replaced; the old one stops working
  GET  /v2/chats/join/<token>     no sign-in: {name}, whose link it is, for the
                                   join page; 404 for a wrong or replaced link
  POST /v2/chats/join/<token>     {chat: {id}}: the caller's chat with the
                                   link's owner, made once for the two (N328);
                                   400 OWN_LINK for your own

Ring row ``chats`` (ring 6): a person without it gets 404 from every route,
as a chat they are not in does. Anything but the three emoji is 400. One
provider call, for a voice note: its transcription (N324), made by
``post_voice`` through the authorized provider with the voice notebook's
adapter, inside the scope ``phase1_provider_route`` opens, so its permit is
the caller's; limited as the notebook's notes are (``llm_limit``). Its words
are kept with the recording and are in no answer here; a note that cannot be
turned into words is sent all the same. A voice note is a speaker's
recording, and ``/v2/chats`` is outside the core gate's prefixes, so its
upload passes the processing-authorization path itself, after the ring and
the chat (404) and before the recording is looked at (400, 413):
``phase1_provider_route``, as the voice notebook's notes, then the recording
consent a Take asks for (``require_current``, operation "recording", in every
gate mode). A refusal
answers as those do, ``{code, error}`` with its status (403
PROCESSING_RECORDING_WITHDRAWN, 403 PROCESSING_AUTHORIZATION_REQUIRED, ...),
and nothing is written.

A photo or a file (N351) is neither a recording of the speaker nor a provider
call: nothing reads it but the chat's two members, so its routes take the
ring and the chat (404) and the file (400, 413), and no processing
authorization. It is served with ``nosniff`` and a sandbox, a photo inline and
a file as an attachment, so nothing sent can run as a page of ours.
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
from services.rate_limits import client_ip, limiter, llm_limit

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
@llm_limit
def v2_chats_voice(thread_id):
    """A voice note. Its checks in order: the ring and the chat (404); the
    caller's processing authorization (``phase1_provider_route``) and
    recording consent (their refusal); the recording (400, 413). Then its
    message and its recording are written, and the recording is turned into
    words under the same authorization: the adapter the notebook's notes use,
    the one ``phase1_provider_route`` bound when the gate is on (N324). The
    answer is the message, never its words."""
    refused = _recording_refused()
    if refused is not None:
        return refused
    from routes.v2.voice_notebook import _adapter
    from services.chats import MAX_VOICE_BYTES, post_voice
    user_id = str(request.user_id)
    upload = request.files.get("audio")
    # One byte past the limit is enough to know it is over (413).
    audio = upload.stream.read(MAX_VOICE_BYTES + 1) if upload is not None else b""
    content_type = upload.content_type if upload is not None else None
    # The transcriber reads the type from the name's ending, which the app
    # gives by the recording's type (voice.webm, voice.m4a, voice.ogg).
    filename = (upload.filename if upload is not None else None) or "voice.webm"
    return _run("voice", lambda: post_voice(
        db, user_id, thread_id, audio, adapter=_adapter(user_id), filename=filename,
        content_type=content_type, duration_ms=request.form.get("duration_ms")))


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


def _sent(thread_id, kind):
    """A photo or a file from the "+" (N351), multipart ``file``. One byte
    past the limit is enough to know it is over (413)."""
    from services.chats import MAX_FILE_BYTES, post_file
    upload = request.files.get("file")
    data = upload.stream.read(MAX_FILE_BYTES + 1) if upload is not None else b""
    return _run(kind, lambda: post_file(
        db, str(request.user_id), thread_id, kind, data,
        content_type=upload.content_type if upload is not None else None,
        file_name=upload.filename if upload is not None else None))


@v2_bp.route("/chats/<thread_id>/photo", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_photo")
@require_auth
def v2_chats_photo(thread_id):
    return _sent(thread_id, "photo")


@v2_bp.route("/chats/<thread_id>/file", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_file")
@require_auth
def v2_chats_file(thread_id):
    return _sent(thread_id, "file")


@v2_bp.route("/chats/<thread_id>/messages/<message_id>/file", methods=["GET"])
@require_auth
def v2_chats_file_read(thread_id, message_id):
    """A photo or a file, for any member of its chat: a photo shown in place,
    anything else downloaded under its own name; never sniffed, sandboxed."""
    from services.chats import PHOTO_TYPES, sent_file

    def served(got):
        response = send_file(io.BytesIO(got["data"]), mimetype=got["content_type"],
                             as_attachment=got["content_type"] not in PHOTO_TYPES,
                             download_name=got["file_name"], conditional=True)
        response.headers["Cache-Control"] = "private, max-age=3600"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "sandbox"
        return response
    return _run("file", lambda: sent_file(db, str(request.user_id), thread_id, message_id),
                answer=served)


@v2_bp.route("/chats/demo", methods=["POST"])
@require_auth
def v2_chats_demo():
    from services.chats import seed_demo
    return _run("demo", lambda: seed_demo(db, str(request.user_id)))


# ── The join link (services/chat_links.py; N308, N328, N335) ─────────────

@v2_bp.route("/chats/link", methods=["GET"])
@require_auth
def v2_chats_my_link():
    from services.chat_links import my_link
    payload = getattr(request, "token_payload", None)
    return _run("link", lambda: my_link(db, str(request.user_id), payload))


@v2_bp.route("/chats/link", methods=["POST"])
@limiter.limit("10 per hour", scope="chats_link_renew")
@require_auth
def v2_chats_renew_link():
    from services.chat_links import renew
    payload = getattr(request, "token_payload", None)
    return _run("renew", lambda: renew(db, str(request.user_id), payload))


@v2_bp.route("/chats/join/<token>", methods=["GET"])
@limiter.limit("60 per hour", key_func=client_ip, scope="chats_join_preview")
def v2_chats_join_preview(token):
    """The join page's read, before anyone signs in: whose link it is."""
    from services.chat_links import preview
    return _run("preview", lambda: preview(db, token))


@v2_bp.route("/chats/join/<token>", methods=["POST"])
@limiter.limit("30 per hour", scope="chats_join")
@require_auth
def v2_chats_join(token):
    from services.chat_links import join
    payload = getattr(request, "token_payload", None)
    return _run("join", lambda: join(db, str(request.user_id), token, payload))
