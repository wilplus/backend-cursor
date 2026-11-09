"""The model launchpad's routes: the list of AI models, a model's page,
teaching it, the one queue (N528, N563, N566; services/model_launchpad.py
for the rules, services/model_launchpad_store.py for the tables).

  GET  /v2/models                          {intro, filters, drafts, models, empty?}
                                           ?q=<search>&filter=for_you|ready|learning
  GET  /v2/models/rows                     {rows}: "Your queue" and "AI models"
  GET  /v2/models/door                     the disclaimer at the door
  GET  /v2/models/what-do-i-get            the three short cards
  GET  /v2/models/queue                    the one queue; ?only=<model id>
  GET  /v2/models/<id>                     a model's page for the caller, or 404
  POST /v2/models/<id>/enter               "This is my field"
  POST /v2/models/<id>/pause               {paused: bool}
  POST /v2/models/<id>/examples/<eid>/answer   {step, answer}
  GET  /v2/models/profile/<user_id>        the profile's "AI models", or null
  GET  /v2/models/invites/<id>             an invite to teach, as it stays
  GET  /v2/models/invites                  the caller's invites, open or put off
  POST /v2/models/invites/<id>/not-now     "Not now": it stays
  POST /v2/models/invites/<id>/accept      the caller teaches the model
  POST /v2/models/<id>/examples            {text | transcript, step?, answer?}: an example added
  POST /v2/models/<id>/archive             the owner's Archive
  POST /v2/models/<id>/make-public         {confirm: true}, after the disclaimer
  GET  /v2/models/<id>/download            the teachers' ratings and answers, never the exam
  POST /v2/models/<id>/transcribe          a spoken answer or case (multipart ``audio``)
                                           to its words: {transcript}

Ring row ``ai_models`` (ring 6): anyone else gets 404 from every route. One
provider call: ``/transcribe``, "Record your answer" (MOD-20) and "Record
one" (MOD-21). It passes the path a chat's voice note does: the model is
the caller's to teach (404), the caller's processing authorization
(``phase1_provider_route``) and their recording consent (their refusal),
then the recording is turned into words under that authorization. The
recording is never kept: only its words come back, and only they reach a
model (N528 item 10).
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.rate_limits import llm_limit
from services.db import db

logger = logging.getLogger(__name__)


def _run(label: str, work):
    from services.chats import ChatsError
    try:
        result = work()
    except ChatsError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("models %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to reach the models"}), 500
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200


def _me() -> str:
    return str(getattr(request, "user_id", ""))


@v2_bp.route("/models", methods=["GET"])
@require_auth
def v2_models_list():
    from services import model_launchpad_store as store
    return _run("list", lambda: store.list_for(db, _me(), query=request.args.get("q", ""),
                                               filter_=request.args.get("filter") or None))


@v2_bp.route("/models/rows", methods=["GET"])
@require_auth
def v2_models_rows():
    from services import model_launchpad_store as store
    return _run("rows", lambda: store.chat_rows_for(db, _me()))


@v2_bp.route("/models/door", methods=["GET"])
@require_auth
def v2_models_door():
    from services import model_launchpad as rules
    from services import model_launchpad_store as store
    return _run("door", lambda: (store._require(db, _me()), rules.door())[1])


@v2_bp.route("/models/what-do-i-get", methods=["GET"])
@require_auth
def v2_models_what_do_i_get():
    from services import model_launchpad as rules
    from services import model_launchpad_store as store
    return _run("what", lambda: (store._require(db, _me()), rules.what_do_i_get())[1])


@v2_bp.route("/models/queue", methods=["GET"])
@require_auth
def v2_models_queue():
    from services import model_launchpad_store as store
    return _run("queue", lambda: store.queue_for(db, _me(), only=request.args.get("only")))


@v2_bp.route("/models/profile/<user_id>", methods=["GET"])
@require_auth
def v2_models_profile(user_id):
    from services import model_launchpad_store as store
    return _run("profile", lambda: {"section": store.profile_for(db, _me(), user_id)})


@v2_bp.route("/models/invites/<invite_id>", methods=["GET"])
@require_auth
def v2_models_invite(invite_id):
    from services import model_launchpad_store as store
    return _run("invite", lambda: store.invite_for(db, _me(), invite_id))


@v2_bp.route("/models/<model_id>", methods=["GET"])
@require_auth
def v2_models_page(model_id):
    from services import model_launchpad_store as store
    return _run("page", lambda: store.page_for(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/enter", methods=["POST"])
@require_auth
def v2_models_enter(model_id):
    from services import model_launchpad_store as store
    return _run("enter", lambda: store.enter(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/pause", methods=["POST"])
@require_auth
def v2_models_pause(model_id):
    from services import model_launchpad_store as store
    body = request.get_json(silent=True) or {}
    return _run("pause", lambda: store.set_paused(db, _me(), model_id, bool(body.get("paused"))))


@v2_bp.route("/models/<model_id>/examples/<example_id>/answer", methods=["POST"])
@require_auth
def v2_models_answer(model_id, example_id):
    from services import model_launchpad_store as store
    body = request.get_json(silent=True) or {}
    # A spoken answer arrives as its words: the transcript of the recording
    # made through the chats' recording path (MOD-20).
    value = body.get("answer") if body.get("answer") is not None else body.get("transcript")
    return _run("answer", lambda: store.answer(db, _me(), example_id, model_id,
                                               str(body.get("step") or "rate"), value))


@v2_bp.route("/models/invites", methods=["GET"])
@require_auth
def v2_models_invites():
    from services import model_launchpad_store as store
    return _run("invites", lambda: store.invites_for(db, _me()))


@v2_bp.route("/models/invites/<invite_id>/not-now", methods=["POST"])
@require_auth
def v2_models_invite_not_now(invite_id):
    from services import model_launchpad_store as store
    return _run("not-now", lambda: store.answer_invite(db, _me(), invite_id, accept=False))


@v2_bp.route("/models/invites/<invite_id>/accept", methods=["POST"])
@require_auth
def v2_models_invite_accept(invite_id):
    from services import model_launchpad_store as store
    return _run("accept", lambda: store.answer_invite(db, _me(), invite_id, accept=True))


@v2_bp.route("/models/<model_id>/examples", methods=["POST"])
@require_auth
def v2_models_add_example(model_id):
    from services import model_launchpad_store as store
    body = request.get_json(silent=True) or {}
    return _run("add", lambda: store.add_example(db, _me(), model_id, body))


@v2_bp.route("/models/<model_id>/archive", methods=["POST"])
@require_auth
def v2_models_archive(model_id):
    from services import model_launchpad_store as store
    return _run("archive", lambda: store.archive(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/make-public", methods=["POST"])
@require_auth
def v2_models_make_public(model_id):
    from services import model_launchpad_store as store
    body = request.get_json(silent=True) or {}
    return _run("public", lambda: store.make_public(db, _me(), model_id, body.get("confirm") is True))



@v2_bp.route("/models/<model_id>/download", methods=["GET"])
@require_auth
def v2_models_download(model_id):
    from services import model_launchpad_store as store
    return _run("download", lambda: store.download(db, _me(), model_id))


#: A spoken answer or case: two minutes at most, as a chat's voice note.
_MAX_SPOKEN_BYTES = 12 * 1024 * 1024


def _a_teacher_first(function):
    """The ring and the model first: 404 unless the caller teaches it, before
    the processing authorization is asked."""
    from functools import wraps

    @wraps(function)
    def wrapped(model_id, *args, **kwargs):
        from services import model_launchpad_store as store
        from services.chats import ChatsError
        try:
            store.teaches(db, _me(), model_id)
        except ChatsError as e:
            return jsonify({"code": e.code, "error": str(e)}), e.status
        return function(model_id, *args, **kwargs)
    return wrapped


@v2_bp.route("/models/<model_id>/transcribe", methods=["POST"])
@require_auth
@_a_teacher_first
@phase1_provider_route
@llm_limit
def v2_models_transcribe(model_id):
    """A spoken answer or case to its words, under the caller's processing
    authorization and recording consent, as a chat's voice note is (N324)."""
    from routes.v2.chats import _recording_refused
    refused = _recording_refused()
    if refused is not None:
        return refused
    from routes.v2.voice_notebook import _adapter
    from services import model_launchpad_store as store
    upload = request.files.get("audio")
    audio = upload.stream.read(_MAX_SPOKEN_BYTES + 1) if upload is not None else b""
    kind = upload.content_type if upload is not None else None
    filename = (upload.filename if upload is not None else None) or "voice.webm"
    user_id = _me()
    return _run("transcribe", lambda: store.transcribe(
        audio, kind, filename, adapter=_adapter(user_id), user_id=user_id, model_id=model_id,
        most=_MAX_SPOKEN_BYTES))
