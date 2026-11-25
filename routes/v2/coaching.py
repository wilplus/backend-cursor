"""The conversational surface: /chat/query, /chat/voice and /chat/session-state.

The coaching lane that lived beside them (start / get / turn / the 9-step
state-machine turn / intro bubble / snippet follow-up) lost its route
decorators in the Phase-1 processing-boundary change (48dd721, 2026-08-29)
and was deleted in Phase 6 (audit Q-A6) together with the charisma/stress
skills it drew its prompts from — retired construct, no caller. The
onboarding dad-joke opener and the interview question-generation module
(routes/v2/user_chat.py) went the same way (audit Q-A7).

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 5);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Formerly re-exported from the ``routes.v2_routes`` façade (removed 2026-09-14,
audit Q-A3); import from this module.
"""
import logging

import sentry_sdk
from flask import jsonify, request

import json
from typing import Any, Optional

from auth import optional_auth, require_auth
from routes.v2.common import _resolve_snippet_audio_url
from services.rate_limits import llm_limit
from config import Config
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.chat_query import (
    answer_chat, chat_turn_id, claim_chat_turn, complete_chat_turn_claim,
    finish_chat_turn, is_chat_turn_id, replay_chat_turn, terminal_error_response,
)
from services.db import db
from services.snippet_values import resolve_all

logger = logging.getLogger(__name__)
config = Config()

#: The v2_sessions columns GET /chat/session-state answers with.
_SESSION_STATE_COLUMNS = (
    "id,created_at,results_published_at,"
    "session_kpi_narrative_ai_draft,ai_task_alignment_comment"
)


@v2_bp.route("/chat/session-state", methods=["GET"])
@require_auth
def v2_chat_session_state():
    """Drive the /chat route's UI state for a returning user.

    The frontend killed the /results page; /chat is now the
    single destination after onboarding. This endpoint tells it
    what mode to render in.

    State machine::

        NO_SESSION     — user has no v2_sessions row at all (fresh
                          signup, never recorded). Frontend should
                          route them into the onboarding interview.

        PENDING_COACH  — latest session exists but
                          results_published_at IS NULL (admin
                          hasn't reviewed + published yet).
                          Frontend renders the waiting / FAQ chat;
                          POST /v2/chat/query is fully usable
                          against the Master Document in this
                          state.

        REVIEW_LOOP    — latest session has been published. Payload
                          includes the snippets + admin_comments
                          so the frontend can drop straight into
                          the snippet-review chat without a second
                          round-trip to /v2/user/results/<id>.

    Response (200)::

        {
          "state": "NO_SESSION" | "PENDING_COACH" | "REVIEW_LOOP",
          "session_id": "<uuid>" | null,
          "created_at": "<iso8601>" | null,
          "results_published_at": "<iso8601>" | null,

          // present iff state == "REVIEW_LOOP"
          "snippets":         [ ... full snippet objects, see below ],
          // kpi_score + charisma_profile removed (AC-9 — classifier/
          // appraisal data is never serialized to the user).
          "ai_summary":       string | null
        }

    Each REVIEW_LOOP snippet matches the shape /user/results/<id>
    returns so the frontend can reuse its existing renderer
    without a second translation layer.

    Why a separate endpoint when /user/sessions/current exists:
    /sessions/current emits the legacy 5-status vocabulary
    (no_session / processing / pending_review / completed /
    error). The frontend's /chat router wants the new
    3-state vocabulary explicitly + the snippet payload inline.
    We could overload /sessions/current, but doing that risks
    breaking the homework + admin routing surfaces that read
    its current shape. A dedicated endpoint is cheaper.
    """
    try:
        user_id = request.user_id
        # Only what the answer below carries: the row's blobs (transcripts,
        # profiles, context) would otherwise ride along on every /chat open.
        session = db.takes.v2_get_latest_session_for_user(
            user_id, columns=_SESSION_STATE_COLUMNS)

        if not session:
            return jsonify({
                "state": "NO_SESSION",
                "session_id": None,
                "created_at": None,
                "results_published_at": None,
            }), 200

        session_id = str(session.get("id"))
        published_at = session.get("results_published_at")
        base = {
            "session_id": session_id,
            "created_at": session.get("created_at"),
            "results_published_at": published_at,
        }

        if not published_at:
            # Admin hasn't clicked Publish yet. The /v2/chat/query
            # endpoint is the right surface for the user to ask
            # questions while they wait — same Master-Document
            # grounding, no special-casing needed here.
            return jsonify({"state": "PENDING_COACH", **base}), 200

        # REVIEW_LOOP — load published snippets in the same shape
        # /user/results/<id> uses, so the frontend renderer is
        # reusable. We resolve audio URLs the same way too: the
        # admin Files tab, the /results page, and this endpoint all
        # serve the same playable URL.
        try:
            raw_snippets = db.v2_get_results_snippets_for_session(
                session_id, user_id,
            ) or []
        except Exception as snip_err:
            logger.warning(
                "chat/session-state: snippet load failed sid=%s err=%s",
                session_id, snip_err,
            )
            raw_snippets = []

        snippets = [
            {
                "id": s.get("id"),
                "admin_comment": s.get("admin_comment"),
                "audio_url": _resolve_snippet_audio_url(s),
                "transcript": s.get("transcript"),
                "turn_number": s.get("turn_number"),
                "question_text": s.get("question_text"),
                "start_offset_ms": s.get("start_offset_ms") or 0,
                "duration_ms": s.get("duration_ms"),
                # PM-9: the six denormalized columns are dead on the live
                # path (services/snippet_values) — this block returned six
                # NULLs for every auto-extracted snippet, which is every
                # snippet the lab pipeline makes. Resolve against the blob.
                "metrics": resolve_all(s),
            }
            for s in raw_snippets
        ]

        # Phase 18.x split-sinks Option A — ai_summary surfaces the
        # immutable AI draft so admin edits don't leak to the user.
        return jsonify({
            "state": "REVIEW_LOOP",
            **base,
            "snippets": snippets,
            "ai_summary": (
                session.get("session_kpi_narrative_ai_draft")
                or session.get("ai_task_alignment_comment")
            ),
        }), 200

    except Exception as e:
        logger.error(
            "chat/session-state failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to evaluate session state",
        }), 500


def _project_coordinates(body) -> tuple[str | None, str | None]:
    def value(key):
        candidate = body.get(key)
        return candidate.strip() or None if isinstance(candidate, str) else None
    return value("arc_id"), value("session_id")


def _parse_chat_request(req) -> dict:
    """Normalize JSON and multipart chat requests into one transport shape.

    Invalid optional metadata degrades to its neutral value exactly as before;
    validation of the required question remains the route's responsibility.
    """
    is_multipart = "multipart/form-data" in (req.content_type or "").lower()
    parsed: dict[str, Any] = {
        "question": None,
        "history": None,
        "presentation_context": {},
        "persist_thread": False,
        "user_client_id": None,
        "request_id_conflict": False,
        "user_created_at": None,
        "screen": False,
        # The chat the turn is typed in (N635): its rows are stamped with it.
        "place": None,
        "project_id": None,
        "take_id": None,
        # The speaker's own chat the turn is typed in (N700).
        "own_chat": None,
    }
    if not is_multipart:
        body = req.get_json(silent=True) or {}
        parsed["project_id"], parsed["take_id"] = _project_coordinates(body)
        parsed["question"] = body.get("question")
        history = body.get("history")
        parsed["history"] = history if isinstance(history, list) else None
        parsed["screen"] = body.get("history_source") == "screen"
        parsed["persist_thread"] = bool(body.get("persist"))
        client_id = body.get("client_id")
        request_id = body.get("request_id")
        client_id = client_id if isinstance(client_id, str) else None
        request_id = request_id if isinstance(request_id, str) else None
        parsed["user_client_id"], parsed["request_id_conflict"] = \
            _correlated_request_id(client_id, request_id)
        created_at = body.get("client_created_at")
        parsed["user_created_at"] = created_at \
            if isinstance(created_at, str) else None
        context = body.get("presentation_context")
        parsed["presentation_context"] = context \
            if isinstance(context, dict) else {}
        place = body.get("place")
        parsed["place"] = place if isinstance(place, str) else None
        parsed["own_chat"] = _own_chat_id(body.get("own_chat"))
        return parsed

    parsed["question"] = (req.form.get("question") or "").strip()
    parsed["project_id"], parsed["take_id"] = _project_coordinates(req.form)
    parsed["own_chat"] = _own_chat_id(req.form.get("own_chat"))
    history_raw = req.form.get("history")
    if history_raw:
        try:
            history = json.loads(history_raw)
            parsed["history"] = history if isinstance(history, list) else None
        except Exception:
            pass

    presentation_raw = req.form.get("presentation_context")
    if presentation_raw:
        try:
            context = json.loads(presentation_raw)
            parsed["presentation_context"] = context \
                if isinstance(context, dict) else {}
        except Exception:
            pass

    parsed["persist_thread"] = (
        (req.form.get("persist") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    parsed["screen"] = (req.form.get("history_source") or "").strip() == "screen"
    client_id = req.form.get("client_id") or None
    request_id = req.form.get("request_id") or None
    parsed["user_client_id"], parsed["request_id_conflict"] = \
        _correlated_request_id(client_id, request_id)
    parsed["user_created_at"] = req.form.get("client_created_at") or None
    parsed["place"] = req.form.get("place") or None

    return parsed


def _correlated_request_id(client_id: Any, request_id: Any) -> tuple[Any, bool]:
    """Canonicalise UUID aliases before deciding whether they conflict.

    UUID text is case-insensitive.  Treating an uppercase ``client_id`` and
    lowercase ``request_id`` as different logical turns would turn a safe
    transport retry into a false refusal.  Legacy non-UUID display ids still
    pass through untouched and are deliberately treated as fresh by the
    route, as before.
    """
    client = chat_turn_id(client_id) if is_chat_turn_id(client_id) else None
    request_turn = (
        chat_turn_id(request_id) if is_chat_turn_id(request_id) else None
    )
    return (
        client or request_turn or client_id or request_id,
        bool(client and request_turn and client != request_turn),
    )


def _take_exchange_scope(context):
    inside = context.get("take_exchange") if isinstance(context, dict) else None
    return {"take_exchange": inside} if isinstance(inside, bool) else {}


def _own_chat_id(value) -> Optional[str]:
    """The ``own_chat`` a turn names (N700), or None."""
    return value if isinstance(value, str) and value else None


def _own_chat_scope(transport, user_id) -> dict:
    """The speaker's own chat the turn was typed in (N700): its rows name it,
    and it becomes the chat used last. A chat that is not theirs names none."""
    chat = transport.get("own_chat")
    if not chat or not user_id:
        return {}
    from services import own_chats
    try:
        if not own_chats.owned(db, user_id, chat):
            return {}
        own_chats.touch(db, user_id, chat)
    except Exception as error:  # noqa: BLE001 - the turn is placed by section instead
        logger.info("own chat scope skipped: %s", type(error).__name__)
        return {}
    return {"chat_id": str(chat)}


def _with_own_chat(scope, own: dict):
    return {**(scope or {}), **own} if own else scope


def _claim_project_scope(transport, context):
    if not transport["project_id"]:
        return None
    from services.project_chat import review_anchor

    focus = review_anchor(context.get("review_focus")) if isinstance(context, dict) else None
    return {
        "arc_id": transport["project_id"], "project_chat": True,
        "take_session_id": transport["take_id"], **({"review_focus": focus} if focus else {}),
        **_take_exchange_scope(context),
    }


@v2_bp.route("/chat/voice", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_chat_voice():
    """Transcribe a chat answer without creating a Take or writing a turn."""
    from routes.v2.voice_notebook import _adapter
    from services.chat_voice_attempt import hear
    from services.processing_authorization import ProcessingAuthorizationError
    from services.will_question import QuestionError

    user_id = str(request.user_id)
    try:
        upload = request.files.get("audio")
        if upload is None:
            return jsonify({"code": "EMPTY_AUDIO", "error": "No audio."}), 400
        try:
            duration = int(request.form.get("duration_ms") or 0) or None
        except ValueError:
            duration = None
        project = request.form.get("project_id") or None
        if project:
            from routes.v2.common import _is_valid_uuid
            owner = db.get_owner_principal_for_user(user_id) if _is_valid_uuid(project) else None
            if not owner or not db.get_project_for_owner(project, str(owner["id"])):
                return jsonify({"code": "NOT_FOUND", "error": "Project not found."}), 404
        response = hear(
            _adapter(user_id), upload.read(), user=user_id,
            filename=upload.filename or "answer.webm", duration=duration,
            turn=request.form.get("voice_turn_id"), project=project,
            practice_reply=request.form.get("chat_practice_reply_id"),
        )
        return jsonify(response), 200
    except QuestionError as error:
        return jsonify({"code": error.code, "error": str(error)}), error.status
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    except Exception as error:
        logger.error("chat answer transcription failed", exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({"code": "V2_ERROR", "error": "Failed to transcribe the answer"}), 500


@v2_bp.route("/chat/voice/<turn>", methods=["GET"])
@require_auth
def v2_chat_voice_play(turn):
    from io import BytesIO
    from flask import send_file
    from services.lounge_voice_reply import read
    from services.refusal import Refusal

    try:
        audio, mime = read(db, str(request.user_id), turn)
    except Refusal as error:
        return jsonify(error.body), error.status
    response = send_file(BytesIO(audio), mimetype=mime, conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/chat/voice/<turn>", methods=["POST"])
@phase1_provider_route
@llm_limit
@require_auth
def v2_chat_voice_attach(turn):
    from routes.v2.voice_notebook import _adapter
    from services.lounge_voice_reply import MAX_BYTES, save
    from services.processing_authorization import ProcessingAuthorizationError
    from services.refusal import Refusal

    user = str(request.user_id)
    upload = request.files.get("audio")
    try:
        adapter = _adapter(user)
        adapter.authorization.require_current(adapter.coordinates.acquisition_principal_id, operation="recording")
        audio = upload.stream.read(MAX_BYTES + 1) if upload else b""
        payload = save(db, user, turn, audio, upload.mimetype if upload else "",
                       request.form.get("voice_receipt") or "")
        return jsonify(payload), 200
    except Refusal as error:
        return jsonify(error.body), error.status
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    except Exception as error:  # noqa: BLE001 — avoid recording audio bytes from a rejected database row.
        logger.warning("chat voice attachment failed: %s", type(error).__name__)
        return jsonify({"code": "VOICE_ATTACHMENT_FAILED"}), 503


@v2_bp.route("/chat/query", methods=["POST"])
@phase1_provider_route
@llm_limit
@optional_auth
def v2_chat_query():
    """Unified chat orchestrator for the /chat page.

    Powers the post-signup single-thread chat surface. The LLM
    runs under services.master_doc_rag with the verbatim Master
    Document as its only source of truth, plus capability-boundary
    + upload-intent rules. Returns structured output the frontend
    uses to drive UI state (showing/hiding the upload dropzone).

    Body::

        {
          "question": "what is this?",
          "history":  [                          // optional
            { "role": "user",      "content": "..." },
            { "role": "assistant", "content": "..." }
          ],
          // "screen": history is every bubble the Lounge draws, in its
          // order, cards and asks included (founder 2026-10-20); Will reads
          // it instead of the stored thread. Optional.
          "history_source": "screen",
          // #2 — BE-owned thread persistence (signed-in only). Opt-in: when
          // persist=true, the user + bot turns are written to lounge_messages
          // server-side so they survive reload + relogin (no race-prone FE
          // append). client_id = the user message's FE id (idempotency +
          // dedupe with the FE's optimistic copy); client_created_at = its
          // FE timestamp (ordering). All optional; ignored when signed out.
          "persist":           bool,             // optional, default false
          "client_id":         "uuid",           // optional (user msg id)
          "request_id":        "uuid",           // client_id alias
          "client_created_at": "iso8601"         // optional (user msg ts)
        }

    Responses::

        200 {
              "answer":         str,    # the chat bubble text
              "bubbles":        [str],  # pre-split chat bubbles (FE #157)
              "show_record_ui": bool,   # per-turn record affordance
                                         # toggle (RULE I) — in-app mic
              "suggested_action": str | None,  # the one contextual button
              "suggested_actions": [str],      # deliberate pair, when needed
              "debug":          {...},  # model + history_used / error
              "client_id":      "uuid", # logical turn / retry key
              "request_id":     "uuid", # same value; response correlation
              "terminal":       true,    # typing state may settle now
              "outcome":        "reply" | "structured" | "recoverable_error",
              "retryable":      bool,
              "timeout":        bool,
              "failure": { "code", "retryable", "timeout",
                           "retry_after_ms"?: int } | null,
              # present only when persist=true + signed in:
              "persisted":         bool,   # bot turn written server-side
              "persisted_client_id": str   # the bot row's client_id (FE dedupe)
            }
        400 INVALID_INPUT / INVALID_REQUEST_ID — validation refusal
        200 CHAT_INTERNAL_ERROR — a well-formed accepted turn that could not
             finish still carries the terminal response fields above

    show_record_ui semantics:
      • show_record_ui — TRUE on the turn where the user expressed
        intent to RECORD in-app via the chat's mic ("can I record
        here?", "let me just record it", etc.). RULE I.
      • Per-turn signal — frontend must NOT cache it across turns;
        each answer carries the current state.
      • (show_upload_ui was removed — uploads are off and FE seam-7b
        cleared the field; upload intent still redirects to record
        per RULE G, just without a flag.)

    Why @optional_auth: the willab Lounge is an unsigned-home
    (design §3) — the Lounge bot / librarian must answer without a
    session. Signed-in requests carry request.user_id (so the
    private admin notes layer in); anonymous requests
    get request.user_id=None and the general bot (no per-user reads/
    writes, no DSP attribution). NEVER 401s — signed-out chat works.

    Multipart text remains accepted for compatibility, but this endpoint does
    not accept or analyze voice. Voice processing belongs exclusively to the
    authorized recording boundary.
    """
    turn_id = chat_turn_id()
    claim_id = None
    question = ""
    try:
        transport = _parse_chat_request(request)
        question = transport["question"]
        history = transport["history"]
        presentation_context = transport["presentation_context"]
        persist_thread = transport["persist_thread"]
        supplied_turn_id = transport["user_client_id"]
        user_created_at = transport["user_created_at"]

        if transport["request_id_conflict"]:
            payload = terminal_error_response(
                turn_id, "INVALID_REQUEST_ID", retryable=False,
            )
            payload.update({
                "code": "INVALID_REQUEST_ID",
                "error": "client_id and request_id must match",
            })
            return jsonify(payload), 400
        # Always return a logical turn id.  A caller that wants a retry to be
        # durable sends this same UUID back with persist=true; missing IDs are
        # deliberately fresh so repeated text is not collapsed by its words.
        # Older callers occasionally used display ids instead of UUIDs; treat
        # those as absent and return a usable server id rather than refusing a
        # message that can still be answered safely.
        turn_id = chat_turn_id(
            supplied_turn_id if is_chat_turn_id(supplied_turn_id) else None)

        if not isinstance(question, str) or not question.strip():
            payload = terminal_error_response(
                turn_id, "INVALID_INPUT", retryable=False,
            )
            payload.update({
                "code": "INVALID_INPUT",
                "error": "question must be a non-empty string",
            })
            return jsonify(payload), 400

        # A client can lose the first response and retry with ``persist``
        # accidentally omitted.  A durable receipt still wins over that
        # transport mode switch: never re-run a completed signed-in turn just
        # because the retry did not repeat its persistence preference.
        if request.user_id and is_chat_turn_id(supplied_turn_id):
            replay = replay_chat_turn(db, request.user_id, turn_id, question)
            if replay is not None:
                if replay.get("failure") and not replay.get("persisted"):
                    replay["persisted"] = False
                return jsonify(replay), 200

        own = _own_chat_scope(transport, request.user_id)
        if persist_thread and request.user_id:
            claim_id, terminal = claim_chat_turn(
                db, request.user_id, turn_id, question,
                user_created_at=user_created_at, place=transport["place"],
                scope_metadata=_with_own_chat(_claim_project_scope(transport, presentation_context), own),
            )
            if terminal is not None:
                # An early terminal result did not write a bot row. Keep the
                # field explicit for the composer while preserving a replayed
                # completed result's already-true value.
                terminal.setdefault("persisted", False)
                if not terminal.get("persisted"):
                    terminal.pop("persisted_client_id", None)
                # Once a syntactically valid turn reached the durable claim,
                # every terminal outcome is a renderable protocol result.
                # Returning it as 200 prevents generic fetch helpers from
                # discarding its correlation fields before the typing state
                # can settle. Malformed alias/input refusals above remain
                # 4xx.
                return jsonify(terminal), 200

        def _finalize(resp, intent):
            meta = resp.get("row_metadata") or {}
            scope = None
            if transport["project_id"]:
                scope = {
                    "arc_id": transport["project_id"], "project_chat": True,
                    "take_session_id": meta.get("take_session_id") or transport["take_id"],
                    **({"review_focus": meta["review_focus"]} if meta.get("review_focus") else {}),
                    **_take_exchange_scope(presentation_context),
                }
            return jsonify(finish_chat_turn(
                db, resp, user_id=request.user_id, question=question,
                persist_thread=persist_thread, user_client_id=turn_id,
                user_created_at=user_created_at, intent=intent,
                place=transport["place"], request_id=turn_id,
                claim_id=claim_id, scope_metadata=_with_own_chat(scope, own))), 200

        return answer_chat(
            db, user_id=request.user_id, question=question, history=history,
            context=presentation_context, app_config=config,
            finalize=_finalize, user_client_id=turn_id,
            screen=transport["screen"], project_id=transport["project_id"],
            take_id=transport["take_id"], place=transport["place"])

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        # A bot receipt may already be durable if a best-effort post-save
        # action raised unexpectedly.  Its stored terminal result is
        # authoritative; never make this first response disagree with a
        # subsequent same-id replay.
        if claim_id and getattr(request, "user_id", None):
            try:
                replay = replay_chat_turn(
                    db, request.user_id, turn_id, question,
                )
            except Exception as replay_error:  # noqa: BLE001 -- terminal fallback below
                logger.warning("chat/query: post-error replay failed user=%s: %s",
                               request.user_id, replay_error)
                replay = None
            if replay is not None and replay.get("persisted"):
                return jsonify(replay), 200
        payload = terminal_error_response(
            turn_id, "CHAT_INTERNAL_ERROR", retryable=True,
        )
        payload.update({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        })
        if claim_id and getattr(request, "user_id", None):
            payload["persisted"] = False
            complete_chat_turn_claim(
                db, request.user_id, turn_id, claim_id,
                state="failed", response=payload,
            )
        # The composer must be able to consume the correlated terminal body
        # before its ordinary non-2xx handling can discard it.  Validation
        # refusals above remain 4xx; an accepted turn that fails unexpectedly
        # is a recoverable terminal result, not an opaque HTTP failure.
        return jsonify(payload), 200
