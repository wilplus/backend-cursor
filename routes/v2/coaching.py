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
import uuid
from typing import Any

from auth import optional_auth, require_auth
from routes.v2.common import _resolve_snippet_audio_url
from services.rate_limits import llm_limit
from config import Config
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
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


def _persist_chat_turn(
    user_id, question, answer, *, suggested_action=None,
    suggested_actions=None, bubbles=None, product_action=None, intent=None,
    user_client_id=None, user_created_at=None,
):
    """BE-owned persistence of one Lounge chat turn (founder #2 — bubbles must
    never disappear). Writes the user message + the bot reply to lounge_messages
    so the thread survives reload + relogin on ANY device, rather than relying on
    a best-effort FE append that can silently fail or race the auth token.

    Idempotent: client_ids are deterministic (uuid5), so re-posting the same turn
    is a no-op (UNIQUE(user_id, client_id)). The user-turn id prefers the FE's
    own client_id (so it de-dupes with the FE's optimistic local copy + preserves
    merge ordering); the bot-turn id derives from it → exactly one bot row per
    user turn. The bot row carries suggested_action/suggested_actions, bubbles,
    and any validated structured product destination in metadata so the FE
    reconstructs contextual choices on rehydrate. Mirrors the existing
    server-insert pattern (publish 'insights ready' card, session cadence).

    Returns the bot row's client_id (so the FE can de-dupe its optimistic
    bubble) or None on failure. Best-effort — never raises to the route.
    """
    from datetime import datetime as _dt, timezone as _tz

    q = (question or "").strip()
    a = (answer or "").strip()
    if not user_id or not a:
        return None

    def _is_uuid(v):
        try:
            uuid.UUID(str(v))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    # User-turn id: prefer the FE's own (dedupe + merge order); else derive
    # deterministically from the text so an identical re-post stays a no-op.
    if user_client_id and _is_uuid(user_client_id):
        u_id = str(user_client_id)
    else:
        u_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"willab-chat-user:{user_id}:{q}"))
    # Bot-turn id derives from the user-turn id → one bot row per user turn.
    b_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"willab-chat-bot:{u_id}"))

    now_iso = _dt.now(_tz.utc).isoformat()
    u_ts = (user_created_at if isinstance(user_created_at, str)
            and user_created_at.strip() else now_iso)

    rows = []
    if q:
        rows.append({
            "client_id": u_id, "role": "user", "kind": "text",
            "body": q, "metadata": None, "client_created_at": u_ts,
        })
    meta = {"intent": intent}
    if suggested_action:
        meta["suggested_action"] = suggested_action
    if suggested_actions:
        meta["suggested_actions"] = suggested_actions
    if bubbles:
        meta["bubbles"] = bubbles
    if product_action is not None:
        from services.product_discovery import parse_product_action
        parsed_action = parse_product_action({"product_action": product_action})
        if parsed_action is not None:
            meta["product_action"] = parsed_action
    rows.append({
        "client_id": b_id, "role": "bot", "kind": "text",
        "body": a, "metadata": meta, "client_created_at": now_iso,
    })

    try:
        db.insert_lounge_messages(str(user_id), rows)
        return b_id
    except Exception as e:
        logger.warning(
            "chat/query: persist turn failed user=%s: %s", user_id, e)
        return None


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


def _finalize_chat_response(
    resp, *, user_id, question, persist_thread, user_client_id,
    user_created_at, intent=None,
):
    """Persist/charge one completed Chat turn and create its HTTP response."""
    if persist_thread and user_id:
        bot_cid = _persist_chat_turn(
            user_id, question, resp.get("answer"),
            suggested_action=resp.get("suggested_action"),
            suggested_actions=resp.get("suggested_actions"),
            bubbles=resp.get("bubbles"),
            product_action=resp.get("product_action"), intent=intent,
            user_client_id=user_client_id,
            user_created_at=user_created_at,
        )
        resp["persisted"] = bool(bot_cid)
        if bot_cid:
            resp["persisted_client_id"] = bot_cid
    # Charge after answering, never before. Chat is repeatable, so it has no
    # idempotency ref; billing failure must never replace the answer.
    if user_id:
        try:
            from services.token_account import charge as _charge
            _charge(str(user_id), "chat")
        except Exception:
            pass
    return jsonify(resp), 200


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

        def _finalize(resp, *, intent=None):
            """Persist this turn server-side (founder #2) when the FE opted in
            and the caller is signed in, then return the 200. The bot row carries
            suggested_action + bubbles in its metadata so the contextual chip
            (trainings / Ideal Text) reconstructs on
            rehydrate — exactly what was vanishing on relogin. Best-effort: a
            persist failure never fails the chat response."""
            return _finalize_chat_response(
                resp, user_id=request.user_id, question=question,
                persist_thread=persist_thread,
                user_client_id=user_client_id,
                user_created_at=user_created_at, intent=intent,
            )

        # ── Life Panel hashtag router (founder 2026-07-26) — the FIRST
        # intercept, and the feature's ONLY contact point with this file.
        #
        # It fires on a leading `#tag` from a signed-in user who has consented
        # to the Life Panel, and on nothing else. Three guards, cheapest
        # first, so a normal chat turn pays ~nothing:
        #   1. LIFE_PANEL_ENABLED (default 0) — off, and this block is a
        #      boolean check that falls straight through.
        #   2. signed in — anonymous Lounge chat never reaches it.
        #   3. handle_note returns None for an untagged message BEFORE any DB
        #      read, and None for a non-consented user. None ⇒ we do not
        #      touch this turn at all.
        #
        # N3 is the contract: for a non-participating user every response on
        # this endpoint is byte-identical to main. That is why the fall-
        # through is `return None → keep going` rather than any modified
        # answer, and why the whole block is inside its own try/except — a
        # broken Life Panel must cost the panel, never the chat.
        if request.user_id and getattr(config, "LIFE_PANEL_ENABLED", False):
            try:
                from services.life_chat import handle_note
                from services.master_doc_rag import split_answer_into_bubbles
                _ln = handle_note(request.user_id, question.strip())
                if _ln:
                    _ans = _ln.get("answer") or ""
                    # The founder's own words, returned at the moment they
                    # apply — appended only when the wall actually had
                    # something above the relevance floor.
                    _ph = _ln.get("phrase") or {}
                    if _ph.get("body"):
                        _ans = f"{_ans}\n\n“{_ph['body']}”"
                    return _finalize({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {"intent": "life_panel",
                                  "route": _ln.get("route"),
                                  "link": _ln.get("link")},
                    }, intent="life_panel")
            except Exception as _le:
                logger.warning(
                    "chat/query: life-panel intercept failed user=%s: %s",
                    request.user_id, _le,
                )

        # ── Goal-update intercept (Prompt A §6 C4) — BEFORE the librarian.
        # §0: never add rules to master_doc_rag (attention ceiling). A
        # signed-in user saying "change my goal to X" (any language) updates
        # user_settings.profile_goal and gets an in-language confirmation;
        # the librarian is short-circuited for that turn. Cheap pre-gate
        # inside, so normal chat turns spend no extra LLM call. Best-effort:
        # any failure falls through to the normal answer.
        if request.user_id:
            try:
                from services.goal_update import handle_goal_update
                from services.master_doc_rag import split_answer_into_bubbles
                _gu = handle_goal_update(request.user_id, question.strip())
                if _gu and _gu.get("answer"):
                    return _finalize({
                        "answer": _gu["answer"],
                        "bubbles": split_answer_into_bubbles(_gu["answer"]),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {
                            "intent": "goal_update",
                            "new_goal": _gu.get("new_goal"),
                        },
                    }, intent="goal_update")
            except Exception as _ge:
                logger.warning(
                    "chat/query: goal-update intercept failed user=%s: %s",
                    request.user_id, _ge,
                )

        # ── Audit intercept (Prompt C §5) — BEFORE the librarian (§0: no
        # master_doc_rag rule edits). A signed-in user asking for their audit
        # gets a short bubble + the audit button (suggested_action="audit")
        # opening the audits page. Deterministic keyword pre-gate inside, so
        # normal chat pays nothing. Best-effort: any failure falls through.
        # Prompt D: RETIRED by default (the Best-Presentation replaces the
        # audit). AUDIT_SURFACE_ENABLED=1 restores it (endpoints stay dormant).
        if request.user_id and getattr(config, "AUDIT_SURFACE_ENABLED", False):
            try:
                from services.audit_intent import handle_audit_intent
                from services.master_doc_rag import split_answer_into_bubbles
                _ai = handle_audit_intent(request.user_id, question.strip())
                if _ai and _ai.get("suggested_action") == "audit":
                    _ans = _ai.get("answer") or ""
                    return _finalize({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": "audit",
                        "debug": {"intent": "audit"},
                    }, intent="audit")
            except Exception as _ae:
                logger.warning(
                    "chat/query: audit intercept failed user=%s: %s",
                    request.user_id, _ae,
                )

        # Presentation/deck changes are project-boundary decisions, not open-
        # ended coaching prose.  Resolve them deterministically from the
        # current project's explicit state before the general librarian can
        # improvise a mutation or collapse two talks together.
        try:
            from services.presentation_change_intent import (
                handle_presentation_change,
            )
            from services.master_doc_rag import split_answer_into_bubbles
            _pi = handle_presentation_change(
                question.strip(), presentation_context,
            )
            if _pi:
                _ans = _pi["answer"]
                return _finalize({
                    "answer": _ans,
                    "bubbles": split_answer_into_bubbles(_ans),
                    "show_record_ui": False,
                    "suggested_action": None,
                    "suggested_actions": _pi["suggested_actions"],
                    "debug": {"intent": _pi["intent"]},
                }, intent=_pi["intent"])
        except Exception as _pie:
            logger.warning(
                "chat/query: presentation-change intercept failed: %s", _pie,
            )

        # ── Lounge-bot deterministic intercepts (chat-audit 2026-06-21) —
        # BEFORE the librarian (§0: keep these OUT of master_doc_rag's mega-
        # prompt; the attention ceiling is full and the probe grades the LLM
        # path). Crisis (safety) → record CTA (the acquisition lever, #4:
        # show_record_ui + suggested_action="record_again", reversing #119 for
        # CLEAR intent) → off-mission generative deflect. Runs for anonymous +
        # signed-in; the goal/audit intercepts above are signed-in-only + more
        # specific, so they win for those phrasings. Best-effort.
        try:
            from services.chat_intents import detect_chat_intent
            from services.master_doc_rag import split_answer_into_bubbles
            _ci = detect_chat_intent(question.strip())
            if _ci:
                _ans = _ci["answer"]
                return _finalize({
                    "answer": _ans,
                    "bubbles": split_answer_into_bubbles(_ans),
                    "show_record_ui": _ci["show_record_ui"],
                    "suggested_action": _ci["suggested_action"],
                    "debug": {"intent": _ci["intent"]},
                }, intent=_ci["intent"])
        except Exception as _cie:
            logger.warning("chat/query: chat-intent intercept failed: %s", _cie)

        # ── Path A — LLM answer (the only thing the HTTP response
        # carries back). Unchanged from the pre-BE-3 behavior.
        # Pull admin's private notes for this user → don't-ask block
        # in the FAQ chat system prompt. @require_auth guarantees a
        # user_id; best-effort on the DB read.
        # Private admin notes apply only when signed in. Anonymous
        # (unsigned-home, §3) gets the general bot — no per-user reads.
        admin_dont_ask_notes: str | None = None
        if request.user_id:
            try:
                _settings = db.get_user_settings(request.user_id) or {}
                admin_dont_ask_notes = (
                    _settings.get("private_admin_notes") or None
                )
            except Exception as e:
                logger.warning(
                    "chat/query: private_admin_notes load failed "
                    "user=%s: %s", request.user_id, e,
                )

        # BE-9 — the Life Panel's per-user block, for participating users only.
        # Retrieved at request time from the requesting user's OWN rows, capped
        # to the top few by relevance; the renderer in master_doc_rag trims and
        # caps again. Everyone else — flag off, not signed in, not consented —
        # passes None, so their prompt is byte-for-byte what it is today.
        # Best-effort: a failed load costs the grounding, never the answer.
        life_context = None
        if request.user_id and getattr(config, "LIFE_PANEL_ENABLED", False):
            try:
                from services.life_chat import has_consented
                if has_consented(request.user_id):
                    from services.life_engine import life_chat_context
                    life_context = life_chat_context(
                        request.user_id, question.strip())
            except Exception as _lce:
                logger.warning(
                    "chat/query: life context load failed user=%s: %s",
                    request.user_id, _lce,
                )

        from services.master_doc_rag import (
            answer_question, split_answer_into_bubbles,
        )
        payload, debug = answer_question(
            question.strip(),
            history=history,
            admin_dont_ask_notes=admin_dont_ask_notes,
            life_context=life_context,
        )

        # S1 — per-turn intent → the one contextual button the FE renders.
        # ("audit" is set by the audit intercept above, not the librarian, but
        # is a valid enum value so the FE contract stays consistent.)
        _sa = payload.get("suggested_action")
        if _sa not in ("trainings", "audit"):
            _sa = None
        _answer = payload.get("answer", "")
        return _finalize({
            "answer": _answer,
            # FE #157 — pre-split chat bubbles (renders 1:1; falls back to
            # splitting `answer` on blank lines when absent). `answer` stays
            # the fallback.
            "bubbles": split_answer_into_bubbles(_answer),
            "show_record_ui": bool(payload.get("show_record_ui", False)),
            "suggested_action": _sa,
            "debug": debug,
        }, intent=(debug or {}).get("intent") or "faq")

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        }), 500


