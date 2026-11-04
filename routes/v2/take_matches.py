"""Matching people after a Take (N477, N478). Service:
services/take_match.py. Behind the ring row ``take_match``; with no row,
every route of the speaker's answers 404.

  GET  /v2/takes/<session_id>/match       the speaker, after the walk:
                                          {match: {id, pseudonym, role,
                                          practises} | null}; one per Take,
                                          none once sent or closed
  POST /v2/take-matches/<id>/send         the speaker sends it: Will's card
                                          reaches the one suggested;
                                          {match: {id, status: "sent"}}
  POST /v2/take-matches/<id>/close        Not now: {match: {id, status}}
  GET  /v2/take-matches/<id>              the one suggested, once it was sent
                                          to them: {match: {id, status,
                                          pseudonym, role, about, words,
                                          slides, duration_ms}}
  GET  /v2/take-matches/<id>/recording    the Take's voice, for them
  POST /v2/take-matches/<id>/answer       {take: their answer's session id,
                                          duration_ms}: the chat between the
                                          two is made now, with the Take and
                                          the answer; {chat: {id}}

Nothing here calls a provider: the ranking is word overlap. Reading the
Take and hearing it are the speaker's choice, made with Send. The answer
was recorded and uploaded through the processing-authorization path
already; what is asked again is the answerer's recording consent, as the
chats' answer route asks it.
"""
import io

from flask import request, send_file

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.chats import _recording_refused, _run
from services.db import db
from services.rate_limits import limiter


@v2_bp.route("/takes/<session_id>/match", methods=["GET"])
@limiter.limit("120 per hour", scope="take_match_suggest")
@require_auth
def v2_take_match_suggest(session_id):
    from services.take_match import suggest
    return _run("match", lambda: suggest(db, str(request.user_id), session_id))


@v2_bp.route("/take-matches/<match_id>/send", methods=["POST"])
@limiter.limit("60 per hour", scope="take_match_send")
@require_auth
def v2_take_match_send(match_id):
    from services.take_match import chat_name, send
    user_id = str(request.user_id)
    payload = getattr(request, "token_payload", None)
    return _run("match send", lambda: send(db, user_id, match_id,
                                           chat_name(db, user_id, payload)))


@v2_bp.route("/take-matches/<match_id>/close", methods=["POST"])
@require_auth
def v2_take_match_close(match_id):
    from services.take_match import close
    return _run("match close", lambda: close(db, str(request.user_id), match_id))


@v2_bp.route("/take-matches/<match_id>", methods=["GET"])
@require_auth
def v2_take_match_view(match_id):
    from services.take_match import view
    return _run("match view", lambda: view(db, str(request.user_id), match_id))


@v2_bp.route("/take-matches/<match_id>/recording", methods=["GET"])
@require_auth
def v2_take_match_recording(match_id):
    """The Take's voice, for the one it was sent to; byte ranges answered."""
    from services.take_match import recording

    def played(got):
        response = send_file(io.BytesIO(got["audio"]), mimetype=got["content_type"],
                             conditional=True)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response
    return _run("match recording", lambda: recording(db, str(request.user_id), match_id),
                answer=played)


@v2_bp.route("/take-matches/<match_id>/answer", methods=["POST"])
@limiter.limit("60 per hour", scope="take_match_answer")
@require_auth
def v2_take_match_answer(match_id):
    """The answer that opens the chat (N478). The recording consent first,
    as for any answer; then the suggestion (404 unless it was sent to the
    caller) and the Take (404 unless it is the caller's)."""
    refused = _recording_refused()
    if refused is not None:
        return refused
    from services.take_match import answer, chat_name
    user_id = str(request.user_id)
    payload = getattr(request, "token_payload", None)
    body = request.get_json(silent=True) or {}
    return _run("match answer", lambda: answer(
        db, user_id, match_id, body.get("take"), body.get("duration_ms"),
        chat_name(db, user_id, payload)))
