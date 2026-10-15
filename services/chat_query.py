"""One Lounge chat turn (POST /v2/chat/query): which voice answers it, and
what is written once it is answered.

Moved out of ``routes.v2.coaching`` unchanged (founder 2026-10-12: "move logic
out of the backend routes"). The route keeps the processing boundary, the
rate limit, the optional auth, the request parsing and the 500 boundary.

The answer comes from the first of these that claims the turn, in this
order; each is best-effort, and a failure falls through to the next:

  1. the Life Panel hashtag router (signed in, flag on, consented);
  2. the goal-update intercept (signed in);
  3. the audit intercept (signed in, AUDIT_SURFACE_ENABLED);
  4. the presentation-change intercept;
  5. the Lounge-bot deterministic intents (crisis, joke, off-mission);
  6. the librarian (``services.master_doc_rag``), with the admin's private
     notes and the Life Panel context for a participating user.

``finalize`` writes the turn (when the client opted in and is signed in) and
charges after answering, never before.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _offer_row(bot_client_id: str, offer: str, created_at: str) -> dict:
    """A Lounge offer the chat opened (founder 2026-10-14): its own bubble,
    in the shape the Lounge already draws (kind text + metadata.offer), so
    tapping it opens the form. The body is the offer's existing copy."""
    from services.chat_app_context import OFFER_PROMPTS
    return {
        "client_id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                                    f"willab-chat-offer:{bot_client_id}")),
        "role": "bot", "kind": "text", "body": OFFER_PROMPTS[offer],
        "metadata": {"offer": offer}, "client_created_at": created_at,
    }


def _bot_metadata(*, intent, suggested_action, suggested_actions,
                  bubbles) -> dict:
    meta: dict[str, Any] = {"intent": intent}
    if suggested_action:
        meta["suggested_action"] = suggested_action
    if suggested_actions:
        meta["suggested_actions"] = suggested_actions
    if bubbles:
        meta["bubbles"] = bubbles
    return meta


def persist_chat_turn(
    database, user_id, question, answer, *, suggested_action=None,
    suggested_actions=None, bubbles=None, intent=None,
    user_client_id=None, user_created_at=None, offer=None,
    speaker_feedback=False,
):
    """BE-owned persistence of one Lounge chat turn (founder #2 — bubbles must
    never disappear): the user message and the bot reply, in lounge_messages,
    so the thread survives reload and relogin on any device.

    Idempotent: client_ids are deterministic (uuid5), so re-posting the same
    turn is a no-op (UNIQUE(user_id, client_id)). The user-turn id prefers the
    FE's own client_id; the bot-turn id derives from it, so there is exactly
    one bot row per user turn.

    Returns the bot row's client_id, or None on failure. Best-effort."""
    q = (question or "").strip()
    a = (answer or "").strip()
    if not user_id or not a:
        return None
    if user_client_id and _is_uuid(user_client_id):
        u_id = str(user_client_id)
    else:
        u_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"willab-chat-user:{user_id}:{q}"))
    b_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"willab-chat-bot:{u_id}"))
    now_iso = datetime.now(timezone.utc).isoformat()
    u_ts = (user_created_at if isinstance(user_created_at, str)
            and user_created_at.strip() else now_iso)
    rows = []
    if q:
        rows.append({
            "client_id": u_id, "role": "user", "kind": "text",
            "body": q, "client_created_at": u_ts,
            "metadata": {"speaker_feedback": True} if speaker_feedback else None,
        })
    rows.append({
        "client_id": b_id, "role": "bot", "kind": "text", "body": a,
        "metadata": _bot_metadata(
            intent=intent, suggested_action=suggested_action,
            suggested_actions=suggested_actions, bubbles=bubbles),
        "client_created_at": now_iso,
    })
    if offer:
        rows.append(_offer_row(b_id, offer, now_iso))
    try:
        database.insert_lounge_messages(str(user_id), rows)
        return b_id
    except Exception as e:
        logger.warning("chat/query: persist turn failed user=%s: %s", user_id, e)
        return None


def finish_chat_turn(database, resp: dict, *, user_id, question,
                     persist_thread, user_client_id, user_created_at,
                     intent=None) -> dict:
    """Persist and charge one completed turn; the response body."""
    if persist_thread and user_id:
        bot_cid = persist_chat_turn(
            database, user_id, question, resp.get("answer"),
            suggested_action=resp.get("suggested_action"),
            suggested_actions=resp.get("suggested_actions"),
            bubbles=resp.get("bubbles"), intent=intent,
            user_client_id=user_client_id, user_created_at=user_created_at,
            offer=resp.get("offer"),
            speaker_feedback=intent == "speaker_feedback",
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
    return resp


def _reply(answer: str, *, show_record_ui=False, suggested_action=None,
           debug=None, **extra) -> dict:
    from services.master_doc_rag import split_answer_into_bubbles
    return {
        "answer": answer,
        "bubbles": split_answer_into_bubbles(answer),
        "show_record_ui": show_record_ui,
        "suggested_action": suggested_action,
        **extra,
        "debug": debug,
    }


def _life_panel(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """N3: for a non-participating user every response is byte-identical to
    main, so this returns None (keep going) for anything it does not own."""
    from services.life_chat import handle_note
    note = handle_note(user_id, question)
    if not note:
        return None
    answer = note.get("answer") or ""
    # The founder's own words, appended only when the wall had something
    # above the relevance floor.
    phrase = note.get("phrase") or {}
    if phrase.get("body"):
        answer = f"{answer}\n\n“{phrase['body']}”"
    return _reply(answer, debug={"intent": "life_panel",
                                 "route": note.get("route"),
                                 "link": note.get("link")}), "life_panel"


def _goal_update(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """Prompt A §6 C4: "change my goal to X" updates the profile goal and
    confirms in the speaker's language; a cheap pre-gate inside."""
    from services.goal_update import handle_goal_update
    update = handle_goal_update(user_id, question)
    if not (update and update.get("answer")):
        return None
    return _reply(update["answer"], debug={
        "intent": "goal_update", "new_goal": update.get("new_goal")}), "goal_update"


def _audit(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """Prompt C §5 (retired by default, AUDIT_SURFACE_ENABLED=1 restores)."""
    from services.audit_intent import handle_audit_intent
    audit = handle_audit_intent(user_id, question)
    if not (audit and audit.get("suggested_action") == "audit"):
        return None
    return _reply(audit.get("answer") or "", suggested_action="audit",
                  debug={"intent": "audit"}), "audit"


def _presentation_change(_user_id, question, context, _history=None) -> Optional[tuple[dict, str]]:
    """Deck changes are project-boundary decisions, resolved from the
    current project's explicit state before the librarian can improvise."""
    from services.presentation_change_intent import handle_presentation_change
    change = handle_presentation_change(question, context)
    if not change:
        return None
    return _reply(change["answer"],
                  suggested_actions=change["suggested_actions"],
                  debug={"intent": change["intent"]}), change["intent"]


def _chat_intent(_user_id, question, _context, history=None) -> Optional[tuple[dict, str]]:
    """Lounge-bot deterministic intercepts (chat-audit 2026-06-21): crisis →
    record CTA → off-mission deflect; anonymous and signed in alike."""
    from services.chat_intents import detect_chat_intent
    intent = detect_chat_intent(question, history)
    if not intent:
        return None
    return _reply(intent["answer"], show_record_ui=intent["show_record_ui"],
                  suggested_action=intent["suggested_action"],
                  debug={"intent": intent["intent"]}), intent["intent"]


def _intercepts(user_id, app_config) -> list[tuple[str, Callable]]:
    life_on = bool(user_id and getattr(app_config, "LIFE_PANEL_ENABLED", False))
    audit_on = bool(user_id and getattr(app_config, "AUDIT_SURFACE_ENABLED", False))
    chain: list[tuple[str, Callable]] = []
    if life_on:
        chain.append(("life-panel intercept failed user=%s: %s", _life_panel))
    if user_id:
        chain.append(("goal-update intercept failed user=%s: %s", _goal_update))
    if audit_on:
        chain.append(("audit intercept failed user=%s: %s", _audit))
    chain.append(("presentation-change intercept failed: %s", _presentation_change))
    chain.append(("chat-intent intercept failed: %s", _chat_intent))
    return chain


def _admin_notes(database, user_id) -> Optional[str]:
    """The admin's private notes → the don't-ask block. Signed in only."""
    if not user_id:
        return None
    try:
        settings = database.get_user_settings(user_id) or {}
        return settings.get("private_admin_notes") or None
    except Exception as e:
        logger.warning("chat/query: private_admin_notes load failed "
                       "user=%s: %s", user_id, e)
        return None


def _life_context(user_id, question, app_config):
    """BE-9 — the Life Panel's per-user block, participating users only;
    everyone else passes None, so their prompt is unchanged."""
    if not (user_id and getattr(app_config, "LIFE_PANEL_ENABLED", False)):
        return None
    try:
        from services.life_chat import has_consented
        if has_consented(user_id):
            from services.life_engine import life_chat_context
            return life_chat_context(user_id, question)
    except Exception as e:
        logger.warning("chat/query: life context load failed user=%s: %s",
                       user_id, e)
    return None


def _librarian(database, user_id, question, history, app_config,
               context=None) -> tuple[dict, str]:
    """Path A — the librarian's answer. S1: the one contextual button the FE
    renders is kept only when it is a known value.

    The librarian also knows the app's features and, for a signed-in
    speaker, their status card (``services.chat_app_context``); the feature
    it opens becomes a chip, an offer bubble or a link."""
    from services import chat_app_context as app
    if not user_id:
        gate = app.signup_gate(history)
        if gate:
            return _reply(gate, debug={"intent": "signup_gate"}), "signup_gate"
    admin_notes = _admin_notes(database, user_id)
    life_context = _life_context(user_id, question, app_config)
    card = app.status_card(database, user_id) if user_id else None
    from services.master_doc_rag import answer_question
    payload, debug = answer_question(
        question, history=history, admin_dont_ask_notes=admin_notes,
        life_context=life_context,
        app_context={"features": app.features_block(card),
                     "status": app.render_status(card)})
    suggested = payload.get("suggested_action")
    if suggested not in ("trainings", "audit"):
        suggested = None
    answer = payload.get("answer", "")
    action = app.named_feature(question) or payload.get("app_action")
    opened = app.apply_app_action(action, card=card,
                                  signed_in=bool(user_id), context=context)
    if opened.get("suggested_action"):
        suggested = opened["suggested_action"]
    if opened.get("link") and opened["link"] not in answer:
        answer = f"{answer}\n\n{opened['link']}"
    extra = {"offer": opened["offer"]} if opened.get("offer") else {}
    if (debug or {}).get("router_intent") == "speaker_feedback":
        # Kept in the speaker's own thread (services.speaker_feedback).
        return _reply(answer, suggested_action=suggested, debug=debug,
                      **extra), "speaker_feedback"
    return _reply(answer,
                  show_record_ui=bool(payload.get("show_record_ui", False)),
                  suggested_action=suggested, debug=debug, **extra), \
        (debug or {}).get("intent") or "faq"


def answer_chat(database, *, user_id, question: str, history, context,
                app_config, finalize: Callable[[dict, str], Any]) -> Any:
    """Answer one turn and hand it to ``finalize(response, intent)``.

    An intercept is finalized inside its own guard, exactly as the route did:
    a failure anywhere in it falls through to the next one."""
    question = question.strip()
    for failure, intercept in _intercepts(user_id, app_config):
        try:
            claimed = intercept(user_id, question, context, history)
            if claimed:
                return finalize(*claimed)
        except Exception as error:
            args = (user_id, error) if "user=%s" in failure else (error,)
            logger.warning("chat/query: " + failure, *args)
    return finalize(*_librarian(database, user_id, question, history,
                                app_config, context))
