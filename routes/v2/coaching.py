"""The conversational surface: /chat/query and /chat/session-state.

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
from typing import Any

from auth import optional_auth, require_auth
from routes.v2.common import _resolve_snippet_audio_url
from services.rate_limits import llm_limit
from config import Config
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.chat_query import answer_chat, finish_chat_turn
from services.db import db
from services.snippet_values import resolve_all

logger = logging.getLogger(__name__)
config = Config()


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
        session = db.takes.v2_get_latest_session_for_user(user_id)

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
        "user_created_at": None,
    }
    if not is_multipart:
        body = req.get_json(silent=True) or {}
        parsed["question"] = body.get("question")
        history = body.get("history")
        parsed["history"] = history if isinstance(history, list) else None
        parsed["persist_thread"] = bool(body.get("persist"))
        client_id = body.get("client_id")
        parsed["user_client_id"] = client_id \
            if isinstance(client_id, str) else None
        created_at = body.get("client_created_at")
        parsed["user_created_at"] = created_at \
            if isinstance(created_at, str) else None
        context = body.get("presentation_context")
        parsed["presentation_context"] = context \
            if isinstance(context, dict) else {}
        return parsed

    parsed["question"] = (req.form.get("question") or "").strip()
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
    parsed["user_client_id"] = req.form.get("client_id") or None
    parsed["user_created_at"] = req.form.get("client_created_at") or None

    return parsed


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
          // #2 — BE-owned thread persistence (signed-in only). Opt-in: when
          // persist=true, the user + bot turns are written to lounge_messages
          // server-side so they survive reload + relogin (no race-prone FE
          // append). client_id = the user message's FE id (idempotency +
          // dedupe with the FE's optimistic copy); client_created_at = its
          // FE timestamp (ordering). All optional; ignored when signed out.
          "persist":           bool,             // optional, default false
          "client_id":         "uuid",           // optional (user msg id)
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
              # present only when persist=true + signed in:
              "persisted":         bool,   # bot turn written server-side
              "persisted_client_id": str   # the bot row's client_id (FE dedupe)
            }
        400 INVALID_INPUT — question missing or not a string
        500 V2_ERROR

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
    try:
        transport = _parse_chat_request(request)
        question = transport["question"]
        history = transport["history"]
        presentation_context = transport["presentation_context"]
        persist_thread = transport["persist_thread"]
        user_client_id = transport["user_client_id"]
        user_created_at = transport["user_created_at"]

        if not isinstance(question, str) or not question.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "question must be a non-empty string",
            }), 400

        def _finalize(resp, intent):
            return jsonify(finish_chat_turn(
                db, resp, user_id=request.user_id, question=question,
                persist_thread=persist_thread, user_client_id=user_client_id,
                user_created_at=user_created_at, intent=intent)), 200

        return answer_chat(
            db, user_id=request.user_id, question=question, history=history,
            context=presentation_context, app_config=config,
            finalize=_finalize)

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        }), 500


