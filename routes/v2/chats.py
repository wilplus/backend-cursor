"""The chats between people, first slice (founder 2026-10-31, N298 to N316;
the voice note, N321 item 2; the photos and files of the "+", N351).
Service: services/chats.py.

  GET  /v2/chats                  {chats: [{id, kind, title, subtitle,
                                   last: {kind, body, created_at, mine,
                                   meta: {take_index} for a sent Take} | null}]}
  GET  /v2/chats/<id>/messages    {messages: [{id, mine, author, kind, body,
                                   meta, created_at}]}, oldest first; a voice
                                   note also with words, an answer with its
                                   Take's words and slides (each slide's
                                   start in ms, N355)
  POST /v2/chats/<id>/messages    {kind: "emoji", body: "👍" | "👀" | "🙏"};
                                   {message: {...}}
  POST /v2/chats/<id>/voice       multipart: audio (the recording; its type is
                                   kept as it came, e.g. audio/webm;codecs=opus),
                                   duration_ms (1 to 120000); {message: {...,
                                   kind: "voice", body: "", meta: {duration_ms}}}
  POST /v2/chats/<id>/answer      {take: the Take's session id, duration_ms}: an
                                   answer recorded with "Record an answer"
                                   (N363), once its Undo has passed; a voice
                                   message pointing at the caller's own Take,
                                   of any length (N486): {message: {..., kind:
                                   "voice", body: "", meta: {duration_ms,
                                   answer: true, take}}}; the other member's
                                   meta has no take
  POST /v2/chats/<id>/question    the same body: a question recorded with
                                   "Record your question" (N483 item 4), the
                                   same message with meta asked, question and
                                   record_answer true; its Undo is the
                                   answer's
  GET  /v2/chats/<id>/messages/<message_id>/audio
                                   the recording, for any member of the chat
                                   (an answer's: its Take's own)
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
  GET  /v2/chats/<id>/messages/<message_id>/take
                                   a Take sent in the chat (kind "take",
                                   N470): {audio_url, duration_ms, slides:
                                   [{index, title, words}]}, for any member
  GET  /v2/user/takes/send/people {enabled, people: [...]}, whom a Take can
                                   be sent to (services/take_sends.py)
  GET  /v2/user/takes/send/last   {enabled, choice: {all, user_ids} | null}
  POST /v2/user/takes/<id>/send   {all, user_ids}: {enabled, sent: [...]};
                                   409 SENDING_OFF while TAKE_SEND_ENABLED
                                   is off
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
from routes.admin import require_admin
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


# ── Block and Report (services/chat_safety.py; N466) ────────────────────

@v2_bp.route("/chats/<thread_id>/block", methods=["POST"])
@limiter.limit("60 per hour", scope="chats_block")
@require_auth
def v2_chats_block(thread_id):
    from services.chat_safety import block
    return _run("block", lambda: block(db, str(request.user_id), thread_id))


@v2_bp.route("/chats/<thread_id>/block", methods=["DELETE"])
@limiter.limit("60 per hour", scope="chats_block")
@require_auth
def v2_chats_unblock(thread_id):
    from services.chat_safety import unblock
    return _run("unblock", lambda: unblock(db, str(request.user_id), thread_id))


@v2_bp.route("/chats/<thread_id>/report", methods=["POST"])
@limiter.limit("20 per hour", scope="chats_report")
@require_auth
def v2_chats_report(thread_id):
    from services.chat_safety import report
    body = request.get_json(silent=True)
    return _run("report", lambda: report(db, str(request.user_id), thread_id, body))


@v2_bp.route("/admin/chat-reports", methods=["GET"])
@require_admin
def v2_admin_chat_reports():
    """The founder's list of reports, in the CEO panel (N466 item 3)."""
    from services.chat_safety import reports
    return _run("reports", lambda: reports(db))


@v2_bp.route("/admin/chat-reports/<report_id>/handled", methods=["POST"])
@require_admin
def v2_admin_chat_report_handled(report_id):
    from services.chat_safety import handled
    return _run("handled", lambda: handled(db, report_id))


def _a_member_first(view):
    """A recording's first check, a voice note's or an answer's, before its
    processing authorization: the ring and the chat, else 404, as every
    route here answers."""
    @wraps(view)
    def wrapped(thread_id):
        from services.chats import member
        return _run("membership", lambda: member(db, str(request.user_id), thread_id),
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


@v2_bp.route("/chats/<thread_id>/answer", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_answer")
@require_auth
@_a_member_first
def v2_chats_answer(thread_id):
    """An answer recorded with "Record an answer" (N363), sent once its Take
    is uploaded and held for what is left of its Undo (N441 item 3). Its Take was recorded and uploaded through the processing-
    authorization path already, and nothing here calls a provider; what is
    asked again is the recording consent, so a speaker who withdrew it sends
    nothing. Then the chat (404), the Take (404 if not the caller's) and its
    length (400)."""
    refused = _recording_refused()
    if refused is not None:
        return refused
    from services.chats import post_answer
    body = request.get_json(silent=True) or {}
    return _run("answer", lambda: post_answer(
        db, str(request.user_id), thread_id, body.get("take"), body.get("duration_ms"),
        body.get("hold_ms")))


@v2_bp.route("/chats/<thread_id>/question", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_question")
@require_auth
@_a_member_first
def v2_chats_question(thread_id):
    """A question recorded with "Record your question" (N483 item 4, N498),
    sent as an answer is: once its Take is uploaded, held for what is left of
    its Undo, after the recording consent is asked again. Marked for the
    other person to answer ("Record your answer")."""
    refused = _recording_refused()
    if refused is not None:
        return refused
    from services.chats import post_answer
    body = request.get_json(silent=True) or {}
    return _run("question", lambda: post_answer(
        db, str(request.user_id), thread_id, body.get("take"), body.get("duration_ms"),
        body.get("hold_ms"), asks=True))


@v2_bp.route("/chats/<thread_id>/answer/undo", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_answer_undo")
@require_auth
@_a_member_first
def v2_chats_answer_undo(thread_id):
    """Undo (N345 item 2, N441): an answer still held is taken back; Will
    says so in the speaker's chat with him. Records nothing and calls no
    provider."""
    from services.chats import undo_answer
    body = request.get_json(silent=True) or {}
    return _run("answer_undo", lambda: undo_answer(
        db, str(request.user_id), thread_id, body.get("message"), body.get("project")))


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


# ── Asked when they join (services/join_questions.py; N487) ─────────────

@v2_bp.route("/chats/join-questions", methods=["GET"])
@require_auth
def v2_chats_join_questions():
    """The questions I set for whoever joins through my link, or null; "set":
    whether the "+" opens the link (N534)."""
    from services.join_questions import mine
    from services.join_setup import is_set
    uid = str(request.user_id)
    return _run("join-questions", lambda: {"questions": mine(db, uid), "set": is_set(db, uid)})


@v2_bp.route("/chats/join-questions", methods=["PUT"])
@limiter.limit("30 per hour", scope="chats_join_questions")
@require_auth
def v2_chats_join_questions_save():
    from services.join_questions import save
    body = request.get_json(silent=True)
    return _run("join-questions save", lambda: save(db, str(request.user_id), body))


@v2_bp.route("/chats/join-questions/setup", methods=["POST"])
@limiter.limit("60 per hour", scope="chats_join_setup")
@require_auth
def v2_chats_join_setup():
    """"Set them" on the "+"'s note: Will asks the setup in his chat (N503,
    N534). {"started"}: false opens the link at once."""
    from services.join_setup import begin
    return _run("join setup", lambda: begin(db, str(request.user_id)))


@v2_bp.route("/chats/join-questions/setup/again", methods=["POST"])
@limiter.limit("60 per hour", scope="chats_join_setup")
@require_auth
def v2_chats_join_setup_again():
    """"Your questions for people who join ›": the summary again."""
    from services.join_setup import again
    return _run("join setup again", lambda: again(db, str(request.user_id)))


@v2_bp.route("/chats/join-questions/setup/answer", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_join_setup_answer")
@require_auth
def v2_chats_join_setup_answer():
    """A tap, or typed words, under Will's setup question."""
    from services.join_setup import answer
    body = request.get_json(silent=True)
    return _run("join setup answer", lambda: answer(db, str(request.user_id), body))


@v2_bp.route("/chats/<thread_id>/setup/<message_id>", methods=["POST"])
@require_auth
def v2_chats_setup_answer(thread_id, message_id):
    """The joiner's tap on one of the link owner's questions (N487 item 4)."""
    from services.join_questions import answer
    body = request.get_json(silent=True)
    return _run("setup answer", lambda: answer(db, str(request.user_id), thread_id, message_id, body))


# ── The chat builder (services/assistants.py; N578, N579, N586, N588) ──

def _builder_or_404(work):
    """The chat builder's ring (N579 item 2): without it, 404, as a chat
    route answers for what is not yours."""
    from services import assistants
    if not assistants.on(db, str(request.user_id)):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    return work()


@v2_bp.route("/chats/recipe", methods=["GET"])
@require_auth
def v2_chats_recipe():
    """My chat's recipe as kept, the builder's start and what stays locked."""
    from services import assistants
    from services.chat_links import name_of
    payload = getattr(request, "token_payload", None)
    return _builder_or_404(lambda: _run("recipe", lambda: assistants.builder(
        db, str(request.user_id), name_of(payload))))


@v2_bp.route("/chats/recipe", methods=["PUT"])
@limiter.limit("60 per hour", scope="chats_recipe")
@require_auth
def v2_chats_recipe_save():
    """My chat's welcome, first-Take questions and how people answer (N579)."""
    from services import assistants
    body = request.get_json(silent=True)
    return _builder_or_404(lambda: _run("recipe save", lambda: assistants.save(
        db, str(request.user_id), body)))


@v2_bp.route("/chats/recipe/setup/offer", methods=["POST"])
@limiter.limit("30 per hour", scope="chats_recipe_setup")
@require_auth
def v2_chats_recipe_offer():
    """Will says what what you know is worth, with "Set up my chat" (N586 item 5)."""
    from services import chat_setup
    from services.chat_links import name_of
    payload = getattr(request, "token_payload", None)
    return _builder_or_404(lambda: _run("recipe offer", lambda: chat_setup.offer(
        db, str(request.user_id), name_of(payload))))


@v2_bp.route("/chats/recipe/setup", methods=["POST"])
@limiter.limit("60 per hour", scope="chats_recipe_setup")
@require_auth
def v2_chats_recipe_setup():
    """The setup of my chat in Will's chat, one question at a time (N582)."""
    from services import chat_setup
    from services.chat_links import name_of
    payload = getattr(request, "token_payload", None)
    return _builder_or_404(lambda: _run("recipe setup", lambda: chat_setup.begin(
        db, str(request.user_id), name_of(payload))))


@v2_bp.route("/chats/recipe/setup/answer", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_recipe_setup_answer")
@require_auth
def v2_chats_recipe_setup_answer():
    """A tap, or typed words, under Will's setup question."""
    from services import chat_setup
    body = request.get_json(silent=True)
    return _builder_or_404(lambda: _run("recipe setup answer", lambda: chat_setup.answer(
        db, str(request.user_id), body)))


# ── One recording answers everyone who asked (services/question_bundles.py; N584)

@v2_bp.route("/chats/bundles", methods=["GET"])
@require_auth
def v2_chats_bundles():
    """My bundles of questions, in Will's chat: the ones waiting first."""
    from services import question_bundles
    return _builder_or_404(lambda: _run("bundles", lambda: question_bundles.queue(
        db, str(request.user_id))))


@v2_bp.route("/chats/bundles/<bundle_id>", methods=["GET"])
@require_auth
def v2_chats_bundle_who(bundle_id):
    """"See who asked ›": the sheet "Who asked" (N602 item 2)."""
    from services import question_bundles
    return _builder_or_404(lambda: _run("bundle who", lambda: question_bundles.who_asked(
        db, str(request.user_id), bundle_id)))


@v2_bp.route("/chats/bundles/<bundle_id>/<action>", methods=["POST"])
@limiter.limit("120 per hour", scope="chats_bundles")
@require_auth
def v2_chats_bundle_act(bundle_id, action):
    """"Record one answer" ({take, duration_ms}), split ({questions}) or
    merge ({into})."""
    from services import assistants, question_bundles
    if not assistants.on(db, str(request.user_id)):
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    if action == "answer":
        # A recorded answer, as "Record an answer" is: the recording consent
        # is asked again, so a host who withdrew it sends nothing.
        refused = _recording_refused()
        if refused is not None:
            return refused
    work = {"answer": question_bundles.answer, "split": question_bundles.split,
            "merge": question_bundles.merge}.get(action)
    if work is None:
        return jsonify({"code": "NOT_FOUND", "error": "Not found."}), 404
    body = request.get_json(silent=True)
    return _builder_or_404(lambda: _run(f"bundle {action}", lambda: work(
        db, str(request.user_id), bundle_id, body)))


@v2_bp.route("/chats/<thread_id>/host", methods=["GET"])
@require_auth
def v2_chats_host(thread_id):
    """For someone in a host's chat: whose assistant answers, who the host
    is, their first Take's questions and how people answer; {"host": null}
    for a chat that is as it was."""
    from services import assistants
    return _run("host", lambda: {"host": assistants.host_of(db, str(request.user_id), thread_id)})


@v2_bp.route("/me/access", methods=["GET"])
@require_auth
def v2_me_access():
    """By invitation (N471): {"member", "invite_only"}. The app shows a
    waiting account the waitlist; its first ask sends the one waitlist
    email to the founder (services/membership.py)."""
    from services.membership import status
    return _run("access", lambda: status(db, str(request.user_id)))


# ── A person's profile (services/people_profiles.py; N366) ───────────────

def _photo_out(got):
    response = send_file(io.BytesIO(got["data"]), mimetype=got["content_type"], conditional=True)
    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox"
    return response


@v2_bp.route("/profile", methods=["GET"])
@require_auth
def v2_profile_mine():
    from services.people_profiles import mine
    payload = getattr(request, "token_payload", None)
    return _run("profile", lambda: mine(db, str(request.user_id), payload))


@v2_bp.route("/profile", methods=["PATCH"])
@limiter.limit("60 per hour", scope="profile_save")
@require_auth
def v2_profile_save():
    from services.people_profiles import save_mine
    payload = getattr(request, "token_payload", None)
    body = request.get_json(silent=True) or {}
    return _run("profile save", lambda: save_mine(db, str(request.user_id), payload, body))


@v2_bp.route("/profile/photo", methods=["GET"])
@require_auth
def v2_profile_my_photo():
    from services.people_profiles import my_photo
    return _run("profile photo", lambda: my_photo(db, str(request.user_id)), answer=_photo_out)


@v2_bp.route("/profile/photo", methods=["PUT"])
@limiter.limit("30 per hour", scope="profile_photo")
@require_auth
def v2_profile_set_photo():
    """Your photo, multipart ``file``. One byte past 5 MB is enough to know
    it is over (413)."""
    from services.people_profiles import MAX_PHOTO_BYTES, set_photo
    upload = request.files.get("file")
    data = upload.stream.read(MAX_PHOTO_BYTES + 1) if upload is not None else b""
    kind = upload.content_type if upload is not None else None
    return _run("profile photo", lambda: set_photo(db, str(request.user_id), data, kind))


@v2_bp.route("/profile/photo", methods=["DELETE"])
@require_auth
def v2_profile_drop_photo():
    from services.people_profiles import drop_photo
    return _run("profile photo", lambda: drop_photo(db, str(request.user_id)))


@v2_bp.route("/chats/<thread_id>/profile", methods=["GET"])
@require_auth
def v2_chats_their_profile(thread_id):
    from services.people_profiles import theirs
    return _run("their profile", lambda: theirs(db, str(request.user_id), thread_id))


@v2_bp.route("/chats/<thread_id>/profile/photo", methods=["GET"])
@require_auth
def v2_chats_their_photo(thread_id):
    from services.people_profiles import their_photo
    return _run("their photo", lambda: their_photo(db, str(request.user_id), thread_id),
                answer=_photo_out)


# ── Sending a Take to the people you tick (services/take_sends.py; N470,
# N479). Behind TAKE_SEND_ENABLED, default off: the reads answer
# {enabled: false}, the send 409 SENDING_OFF, before anything else runs.

@v2_bp.route("/user/takes/send/people", methods=["GET"])
@require_auth
def v2_take_send_people():
    """{enabled, people: [{user_id, name, title, avatar_url, chat_id,
    last_sent}]}: whom the speaker can send a Take to, "Last sent" first."""
    from services.take_sends import people
    return _run("send people", lambda: people(db, str(request.user_id)))


@v2_bp.route("/user/takes/send/last", methods=["GET"])
@require_auth
def v2_take_send_last():
    """{enabled, choice: {all, user_ids} | null}: the speaker's last choice."""
    from services.take_sends import last
    return _run("send last", lambda: last(db, str(request.user_id)))


@v2_bp.route("/user/takes/<take_id>/send", methods=["POST"])
@limiter.limit("120 per hour", scope="take_send")
@require_auth
def v2_take_send(take_id):
    """{all, user_ids}: the caller's own Take, as their message in their
    chat with each person chosen; {enabled, sent: [{user_id, chat_id,
    message_id}]}. Idempotent; only ever adds people. Its Take was recorded
    and uploaded through the processing-authorization path already and
    nothing here calls a provider; the recording consent is asked again,
    as for an answer, so a speaker who withdrew it sends nothing."""
    from services.chats import ChatsError
    from services.take_sends import is_on, send
    if not is_on():
        error = ChatsError("SENDING_OFF", "Sending a Take is not on yet.", 409)
        return jsonify({"code": error.code, "error": str(error)}), error.status
    refused = _recording_refused()
    if refused is not None:
        return refused
    body = request.get_json(silent=True)
    payload = getattr(request, "token_payload", None)
    return _run("send", lambda: send(db, str(request.user_id), take_id, body, payload))


@v2_bp.route("/chats/<thread_id>/messages/<message_id>/take", methods=["GET"])
@require_auth
def v2_chats_take(thread_id, message_id):
    """"Open Take": {audio_url, duration_ms, slides: [{index, title,
    words}]} of a Take sent in this chat, for a member of it only; never
    its Ideal Text or feedback."""
    from services.take_sends import opened
    return _run("take", lambda: opened(db, str(request.user_id), thread_id, message_id))


@v2_bp.route("/chats/<thread_id>/messages/<message_id>/not-now", methods=["POST"])
@require_auth
def v2_chats_not_now(thread_id, message_id):
    """"Not now" under what someone asked me (N483 item 3, N493 item 3):
    nobody is told; the system keeps it (N504 item 2). {"kept": true}."""
    from services.chat_not_now import record
    return _run("not now", lambda: record(db, str(request.user_id), thread_id, message_id))


# ── Your chat on any website (services/chat_widget.py; N567) ─────────────
# The widget's visitor has no account: these routes take no sign-in (but
# "keep") and read the visitor's secret from one header. Limited by address.

WIDGET_GUEST_HEADER = "X-Willab-Widget-Guest"


def _widget_guest():
    return request.headers.get(WIDGET_GUEST_HEADER, "")


@v2_bp.route("/chats/widget/<token>", methods=["GET"])
@limiter.limit("300 per hour", key_func=client_ip, scope="chats_widget_preview")
def v2_chats_widget_preview(token):
    """The pill's read: whose chat it is, and what a visitor may ask."""
    from services.chat_widget import preview
    return _run("widget_preview", lambda: preview(db, token))


@v2_bp.route("/chats/widget/<token>/start", methods=["POST"])
@limiter.limit("20 per hour", key_func=client_ip, scope="chats_widget_start")
def v2_chats_widget_start(token):
    """"Agree and start": the visitor's chat, made now."""
    from services.chat_widget import start
    body = request.get_json(silent=True) or {}
    return _run("widget_start", lambda: start(db, token, body.get("site")))


@v2_bp.route("/chats/widget/<token>/messages", methods=["GET"])
@limiter.limit("600 per hour", key_func=client_ip, scope="chats_widget_read")
def v2_chats_widget_read(token):
    from services.chat_widget import read
    return _run("widget_read", lambda: read(db, token, _widget_guest()))


@v2_bp.route("/chats/widget/<token>/messages", methods=["POST"])
@limiter.limit("120 per hour", key_func=client_ip, scope="chats_widget_emoji")
def v2_chats_widget_emoji(token):
    from services.chat_widget import emoji
    body = request.get_json(silent=True) or {}
    return _run("widget_emoji", lambda: emoji(db, token, _widget_guest(), body))


@v2_bp.route("/chats/widget/<token>/setup/<message_id>", methods=["POST"])
@limiter.limit("120 per hour", key_func=client_ip, scope="chats_widget_setup")
def v2_chats_widget_setup(token, message_id):
    from services.chat_widget import answer_setup
    body = request.get_json(silent=True) or {}
    return _run("widget_setup", lambda: answer_setup(db, token, _widget_guest(), message_id, body))


@v2_bp.route("/chats/widget/<token>/ask", methods=["POST"])
@limiter.limit("30 per hour", key_func=client_ip, scope="chats_widget_ask")
def v2_chats_widget_ask(token):
    from services.chat_widget import ask
    body = request.get_json(silent=True) or {}
    return _run("widget_ask", lambda: ask(db, token, _widget_guest(), body))


@v2_bp.route("/chats/widget/<token>/messages/<message_id>/audio", methods=["GET"])
@limiter.limit("300 per hour", key_func=client_ip, scope="chats_widget_audio")
def v2_chats_widget_audio(token, message_id):
    """An answer's voice, for the visitor; byte ranges answered."""
    from services.chat_widget import recording

    def played(got):
        response = send_file(io.BytesIO(got["audio"]), mimetype=got["content_type"],
                             conditional=True)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response
    return _run("widget_audio", lambda: recording(db, token, _widget_guest(), message_id),
                answer=played)


@v2_bp.route("/chats/widget/<token>/keep", methods=["POST"])
@limiter.limit("30 per hour", scope="chats_widget_keep")
@require_auth
def v2_chats_widget_keep(token):
    """"Keep this chat": the signed-in caller takes the visitor's seat."""
    from services.chat_widget import keep
    payload = getattr(request, "token_payload", None)
    return _run("widget_keep", lambda: keep(db, str(request.user_id), token, _widget_guest(), payload))
