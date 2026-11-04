"""Matching people after a Take (N477, N478, N485, N486, N493). Service:
services/take_match.py. Behind the ring row ``take_match``; with no row,
every route of the speaker's answers 404.

The speaker:
  GET  /v2/takes/<session_id>/match       after the walk: {match: {id,
                                          pseudonym, role} | null}; one per
                                          Take, none once sent or closed
  POST /v2/take-matches/<id>/send         sends it: an inquiry, a new chat in
                                          the one suggested's list; {match:
                                          {id, status: "sent"}}, the same
                                          even after a Not now (never told)
  POST /v2/take-matches/<id>/close        Not now: {match: {id, status}}
The one suggested:
  GET  /v2/take-matches/inquiries         the inquiries waiting on them:
                                          {inquiries: [{id, state, pseudonym,
                                          role, about, sent_at, name?,
                                          due_at?}]}
  GET  /v2/take-matches/<id>              one inquiry; after Open Take with
                                          the speaker's name and the Take:
                                          words, slides, duration_ms
  POST /v2/take-matches/<id>/accept       "Open Take": the door opens
  POST /v2/take-matches/<id>/decline      "Not now": the chat goes, nobody is
                                          told, never matched again
  GET  /v2/take-matches/<id>/recording    the Take's voice, after Open Take
  POST /v2/take-matches/<id>/answer       {take, duration_ms, hold_ms}: the
                                          answer waits its five seconds for
                                          Undo, then the chat between the two
                                          is made: {sending: {due_at}} or
                                          {chat: {id}}
  POST /v2/take-matches/<id>/undo         the answer taken back in time

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


@v2_bp.route("/take-matches/inquiries", methods=["GET"])
@require_auth
def v2_take_match_inquiries():
    from services.take_match import inquiries
    return _run("match inquiries", lambda: inquiries(db, str(request.user_id)))


@v2_bp.route("/take-matches/<match_id>/accept", methods=["POST"])
@limiter.limit("60 per hour", scope="take_match_accept")
@require_auth
def v2_take_match_accept(match_id):
    from services.take_match import accept
    return _run("match accept", lambda: accept(db, str(request.user_id), match_id))


@v2_bp.route("/take-matches/<match_id>/decline", methods=["POST"])
@limiter.limit("60 per hour", scope="take_match_decline")
@require_auth
def v2_take_match_decline(match_id):
    from services.take_match import decline
    return _run("match decline", lambda: decline(db, str(request.user_id), match_id))


@v2_bp.route("/take-matches/<match_id>/undo", methods=["POST"])
@require_auth
def v2_take_match_undo(match_id):
    from services.take_match import undo
    return _run("match undo", lambda: undo(db, str(request.user_id), match_id))


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
    """The answer that opens the chat (N478, N493 item 5). The recording
    consent first, as for any answer; then the inquiry (404 unless it was
    sent to the caller, 409 before Open Take) and the Take (404 unless it is
    the caller's)."""
    refused = _recording_refused()
    if refused is not None:
        return refused
    from services.take_match import answer, chat_name
    user_id = str(request.user_id)
    payload = getattr(request, "token_payload", None)
    body = request.get_json(silent=True) or {}
    return _run("match answer", lambda: answer(
        db, user_id, match_id, body.get("take"), body.get("duration_ms"),
        chat_name(db, user_id, payload), body.get("hold_ms")))
