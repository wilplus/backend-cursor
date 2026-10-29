"""One Lounge chat turn (POST /v2/chat/query): which voice answers it, and
what is written once it is answered.

Moved out of ``routes.v2.coaching`` unchanged (founder 2026-10-12: "move logic
out of the backend routes"). The route keeps the processing boundary, the
rate limit, the optional auth, the request parsing and the 500 boundary.

The answer comes from the first of these that claims the turn, in this
order; each is best-effort, and a failure falls through to the next:

  1. the feedback check (signed in): an answer to "Did this feedback help
     you?" or "What was missing?" (``services.feedback_check``);
  2. the WhatsApp number (signed in): a number typed under the WhatsApp ask
     (``services.whatsapp_notify.chat_turn``);
  3. the Life Panel hashtag router (signed in, flag on, consented);
  4. the goal-update intercept (signed in);
  5. the audit intercept (signed in, AUDIT_SURFACE_ENABLED);
  6. the presentation-change intercept;
  7. the Lounge-bot deterministic intents (crisis, joke, off-mission);
  8. the librarian (``services.master_doc_rag``), with the admin's private
     notes and the Life Panel context for a participating user.

Will reads the conversation in the order the Lounge draws it (founder
2026-10-20): the client sends what is on screen (``history_source``
"screen"), cards included; an older client's plain turns fall back to the
stored thread (``thread_history``).

``finalize`` writes the turn (when the client opted in and is signed in) and
charges after answering, never before.
"""
from __future__ import annotations

import functools
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


def _take_card_row(bot_client_id: str, take_card: dict, created_at: str) -> dict:
    """The latest Take's Ideal Text card the chat opened (founder 2026-10-16:
    "show me my latest take"): the same row the server posts when a text is
    ready (``arc_notifications``), so the Lounge draws it the same and a
    tap opens that Take's text. Its id follows the bot row, so a repeat
    is a no-op."""
    return {
        "client_id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                                    f"willab-chat-take-card:{bot_client_id}")),
        "role": "bot", "kind": "ideal_text", "body": "Your ideal text is ready.",
        "metadata": {"arc_id": str(take_card["arc_id"]), "variant": "ready",
                     "version": take_card.get("version"),
                     "topic": take_card.get("topic")},
        "client_created_at": created_at,
    }


def _bot_metadata(*, intent, suggested_action, suggested_actions,
                  bubbles, extra=None) -> dict:
    meta: dict[str, Any] = {**(extra or {}), "intent": intent}
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
    user_client_id=None, user_created_at=None, offer=None, take_card=None,
    row_metadata=None, bot_row=True,
):
    """BE-owned persistence of one Lounge chat turn (founder #2 — bubbles must
    never disappear): the user message and the bot reply, in lounge_messages,
    so the thread survives reload and relogin on any device.

    Idempotent: client_ids are deterministic (uuid5), so re-posting the same
    turn is a no-op (UNIQUE(user_id, client_id)). The user-turn id prefers the
    FE's own client_id; the bot-turn id derives from it, so there is exactly
    one bot row per user turn.

    ``bot_row`` False stores the user's turn alone: its reply is a row
    already in the thread (a typed "yes" lets the message after the Take go,
    services/after_take.py).

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
    u_ts = (user_created_at if isinstance(user_created_at, str)
            and user_created_at.strip() else
            datetime.now(timezone.utc).isoformat())
    # The reply sorts under the turn it answers, whatever the browser's
    # clock said for that turn; what the reply opens sorts under it.
    from services.lounge_messages import stamp_after
    now_iso = stamp_after(u_ts)
    if offer:
        # An ask already showing last is not asked again (founder
        # 2026-10-20); the reply still opens its form.
        from services.chat_app_context import newest_ask
        if newest_ask(database, user_id) == offer:
            offer = None
    rows = []
    if q:
        rows.append({
            "client_id": u_id, "role": "user", "kind": "text",
            "body": q, "client_created_at": u_ts,
            "metadata": None,
        })
    if bot_row:
        rows.append({
            "client_id": b_id, "role": "bot", "kind": "text", "body": a,
            "metadata": _bot_metadata(
                intent=intent, suggested_action=suggested_action,
                suggested_actions=suggested_actions, bubbles=bubbles,
                extra=row_metadata),
            "client_created_at": now_iso,
        })
    if offer:
        rows.append(_offer_row(b_id, offer, stamp_after(now_iso)))
    if take_card:
        rows.append(_take_card_row(b_id, take_card, stamp_after(now_iso, gap_ms=2)))
    try:
        database.insert_lounge_messages(str(user_id), rows)
        return b_id
    except Exception as e:
        logger.warning("chat/query: persist turn failed user=%s: %s", user_id, e)
        return None


def _control_after_note(database, user_id) -> bool:
    """Will's answer to a worry under a note (N241 O1); never in the way of
    the note."""
    try:
        from services.in_control import after_note
        return bool(after_note(database, str(user_id)))
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("chat/query: worry answer failed user=%s: %s", user_id, e)
        return False


def _goals_after_note(database, user_id) -> bool:
    try:
        from services.life_goals import after_note
        return bool(after_note(database, str(user_id)))
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("chat/query: life goals ask failed user=%s: %s", user_id, e)
        return False


def finish_chat_turn(database, resp: dict, *, user_id, question,
                     persist_thread, user_client_id, user_created_at,
                     intent=None) -> dict:
    """Persist and charge one completed turn; the response body.

    A turn that passes the Take's open ask advances the chain after the
    Take under the reply: the next ask, or the closing message (founder
    2026-10-20, services/after_take.py)."""
    if persist_thread and user_id:
        bot_cid = persist_chat_turn(
            database, user_id, question, resp.get("answer"),
            suggested_action=resp.get("suggested_action"),
            suggested_actions=resp.get("suggested_actions"),
            bubbles=resp.get("bubbles"), intent=intent,
            user_client_id=user_client_id, user_created_at=user_created_at,
            offer=resp.get("offer"), take_card=resp.get("take_card"),
            row_metadata=resp.get("row_metadata"),
        )
        resp["persisted"] = bool(bot_cid)
        if bot_cid:
            resp["persisted_client_id"] = bot_cid
        from services import after_take
        # True tells the Lounge to read the thread again: the message is there.
        # Never under the safety reply: after a distressed message the asks
        # wait until the speaker writes again (founder 2026-10-21, N94).
        if (bot_cid and intent != "crisis" and after_take.passes(resp)
                and after_take.release(database, user_id)):
            resp["after_take"] = True
        # Under the asked "We spotted a pattern!", the case with Not now |
        # Investigate (N170 L2); the same flag reads the thread again.
        case = resp.pop("sunday_case", None)
        if bot_cid and intent == "sunday_note" and case:
            from services.sunday_note import after_head
            if after_head(database, user_id, case):
                resp["after_take"] = True
        # Under a # note's "Noted.", the ask for life goals (N172 M1); the
        # same flag reads the thread again.
        if (bot_cid and intent == "voice_notebook"
                and (resp.get("row_metadata") or {}).get("voice_note")
                and _goals_after_note(database, user_id)):
            resp["after_take"] = True
        # Under a # note's "Noted.", Will's answer to a worry (N241 O1);
        # the same flag reads the thread again.
        if (bot_cid and intent == "voice_notebook"
                and (resp.get("row_metadata") or {}).get("voice_note")
                and _control_after_note(database, user_id)):
            resp["after_take"] = True
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


def _feedback_check(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """WIL-74: the speaker's answer to the question after the Feedback walk
    is saved and answered with the signed words, before any other voice can
    read it as something else (a goal, a note, feedback for Will)."""
    from services.db import db
    from services.feedback_check import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    meta = turn["row_metadata"]
    extra = {"after_take": turn["after_take"]} if turn.get("after_take") else {}
    return _reply(turn["answer"], suggested_action=meta.get("suggested_action"),
                  row_metadata=meta,
                  debug={"intent": "feedback_check"}, **extra), "feedback_check"


def _will_question(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """N82: what the speaker types under Will's question after a Take (or
    its one follow-up) is their answer: kept, then thanked, before any other
    voice reads it as something else."""
    from services.db import db
    from services.will_question import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    return _reply(turn["answer"], row_metadata=turn["row_metadata"],
                  debug={"intent": "will_question"}), "will_question"


def _whatsapp_number(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """A number typed under the WhatsApp ask (founder 2026-10-20): the form
    opens on its code (N235), before any voice reads it as something else."""
    from services.db import db
    from services.whatsapp_notify import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    extra = {"offer": turn["offer"]} if turn.get("offer") else {}
    return _reply(turn["answer"], row_metadata=turn["row_metadata"],
                  debug={"intent": "whatsapp_number"}, **extra), "whatsapp_number"


def _sunday_note(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """The founder's Sunday note, asked for in any words (Will learning plan,
    step 2, N170 L1): "We spotted a pattern!" (its case row follows the
    turn), or the one bubble that says there is nothing. Anyone else,
    anything else: None."""
    from services.db import db
    from services.sunday_note import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    extra = {"sunday_case": turn["case"]} if turn.get("case") else {}
    return _reply(turn["answer"], row_metadata=turn["row_metadata"],
                  debug={"intent": "sunday_note"}, **extra), "sunday_note"


def _life_goals(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """Life goals asked for in the founder's own words (Will learning plan,
    step 3, N172 M2): "#goals" or "can I add another goal?" is answered and
    opens the lens. Anyone else, anything else: None."""
    from services.db import db
    from services.life_goals import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    return _reply(turn["answer"], row_metadata=turn["row_metadata"],
                  debug={"intent": "life_goals"}), "life_goals"


def _voice_notebook(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """A typed "#" note in the founder's voice notebook (Will learning plan,
    step 1): kept and answered "Noted.", or the question before the first
    note. Not a notebook user, or not a note: None, the chat as before."""
    from services.db import db
    from services.voice_notebook import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    return _reply(turn["answer"], row_metadata=turn["row_metadata"],
                  debug={"intent": "voice_notebook"}), "voice_notebook"


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
    if user_id:
        chain.append(("feedback-check intercept failed user=%s: %s", _feedback_check))
        chain.append(("will-question intercept failed user=%s: %s", _will_question))
        chain.append(("whatsapp-number intercept failed user=%s: %s", _whatsapp_number))
        chain.append(("sunday-note intercept failed user=%s: %s", _sunday_note))
        chain.append(("life-goals intercept failed user=%s: %s", _life_goals))
        chain.append(("voice-notebook intercept failed user=%s: %s", _voice_notebook))
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
    from services import speaker_memory
    from services import voice_notebook as notebook
    from services.feedback_check import CHAT_FACTS as feedback_facts
    from services.will_question import CHAT_FACTS as will_facts
    if not user_id:
        gate = app.signup_gate(history)
        if gate:
            return _reply(gate, debug={"intent": "signup_gate"}), "signup_gate"
    admin_notes = _admin_notes(database, user_id)
    life_context = _life_context(user_id, question, app_config)
    # The status card costs several reads: it is read on first use, once.
    card = functools.cache(
        lambda: app.status_card(database, user_id) if user_id else None)
    # The speaker's private note and the pieces of their own history that
    # match the question (services.speaker_memory), read side by side, once,
    # on first use. Signed-in speakers only.
    from services.parallel import run_in_parallel
    memory = functools.cache(lambda: "".join(run_in_parallel(
        lambda: speaker_memory.prompt_block(speaker_memory.note_for(database, user_id)),
        lambda: speaker_memory.history_for(database, user_id, question),
        lambda: notebook.prompt_block(database, user_id))) if user_id else "")
    from services.master_doc_rag import answer_question
    payload, debug = answer_question(
        question, history=history, admin_dont_ask_notes=admin_notes,
        life_context=life_context,
        app_context=lambda: {"features": app.features_block(card()),
                             "status": app.render_status(card())
                             if user_id else app.VISITOR_BLOCK,
                             "principles": feedback_facts + will_facts if user_id else "",
                             "memory": memory()})
    suggested = payload.get("suggested_action")
    if suggested not in ("trainings", "audit"):
        suggested = None
    answer = payload.get("answer", "")
    action = app.named_feature(question) or payload.get("app_action")
    opened = app.apply_app_action(action, signed_in=bool(user_id),
                                  card=card() if action in ("whatsapp", "latest_take")
                                  else None,
                                  question=question,
                                  context=context)
    if opened.get("suggested_action"):
        suggested = opened["suggested_action"]
    if opened.get("link") and opened["link"] not in answer:
        answer = f"{answer}\n\n{opened['link']}"
    extra = {k: opened[k] for k in ("offer", "take_card") if opened.get(k)}
    if (debug or {}).get("router_intent") == "speaker_feedback":
        # Will answers it like any other turn. Nothing marks it for a
        # person to read (founder 2026-10-15: the chat is as private as any
        # other AI chat; Privacy 3.6 section 4).
        return _reply(answer, suggested_action=suggested, debug=debug,
                      **extra), "faq"
    return _reply(answer,
                  show_record_ui=bool(payload.get("show_record_ui", False)),
                  suggested_action=suggested, debug=debug, **extra), \
        (debug or {}).get("intent") or "faq"


#: Thread rows Will reads as the conversation: chat turns, the summary
#: after a Take (cadence), the walk's steps and the coach's word
#: (walk_step). Status cards are not conversation.
_HISTORY_KINDS = {"text", "joke", "cadence", "walk_step"}
_HISTORY_ROWS = 24


def _retired(row: dict) -> bool:
    """The rows the Lounge hides (frontend isRetiredLoungeMessage)."""
    meta = row.get("metadata") or {}
    return (row.get("kind") == "cadence" and meta.get("beat") == 0) or \
        meta.get("note") in ("human_check", "coach_video_shared")


def _fallback_label(row: dict) -> str:
    """The signed fallback after a Take, told to Will as such (founder
    2026-10-20), so he knows the written summary's specifics are missing;
    the frontend's screen copy says the same. Empty for any other row."""
    meta = row.get("metadata") or {}
    if not (meta.get("summary") is True and meta.get("written") is False):
        return ""
    take = meta.get("take_index")
    which = f"Take {take}" if isinstance(take, int) else "this Take"
    return f"[The app's fixed message after {which}; the written summary failed]\n"


def thread_history(database, user_id, question: str, user_client_id=None) -> list:
    """A signed-in speaker's conversation, read from their own Lounge thread
    (founder 2026-10-15: "it does not hold the context"): the client sends
    only plain chat turns, so a reply to the summary after a Take, a walk
    step or the coach's word arrived with no idea what it answered. Oldest
    first, as {role, content}; this turn's own message (already stored by
    the client) is left out. [] when nothing can be read."""
    try:
        rows = database.get_lounge_messages_page(str(user_id), limit=_HISTORY_ROWS) or []
    except Exception as e:
        logger.warning("chat/query: thread unread user=%s: %s", user_id, e,
                       exc_info=True)
        return []
    turns = []
    for row in reversed(rows):
        body = (row.get("body") or "").strip()
        if (row.get("role") not in ("user", "bot") or not body
                or row.get("kind") not in _HISTORY_KINDS or _retired(row)
                or (user_client_id and row.get("client_id") == user_client_id)):
            continue
        turns.append({"role": "user" if row["role"] == "user" else "assistant",
                      "content": _fallback_label(row) + body})
    if turns and turns[-1]["role"] == "user" and turns[-1]["content"] == question:
        turns.pop()
    return turns


#: The screen as the client sends it: at most this many bubbles, each cut.
_SCREEN_ROWS = 40
_SCREEN_CHARS = 2000


def screen_history(history: Any) -> list:
    """The client's screen (founder 2026-10-20: "the chat should be aware of
    the order of bubbles it displays"): every bubble the Lounge draws, in
    the order it draws them, its cards and asks included, as {role,
    content}. Anything else in the list is dropped. Pure."""
    turns = []
    for m in history if isinstance(history, list) else []:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        content = m.get("content")
        if isinstance(content, str) and content.strip():
            turns.append({"role": m["role"], "content": content.strip()[:_SCREEN_CHARS]})
    return turns[-_SCREEN_ROWS:]


def answer_chat(database, *, user_id, question: str, history, context,
                app_config, finalize: Callable[[dict, str], Any],
                user_client_id=None, screen: bool = False) -> Any:
    """Answer one turn and hand it to ``finalize(response, intent)``.

    ``screen``: the client sent the thread as the Lounge draws it
    (``screen_history``), which is what Will reads. Otherwise a signed-in
    speaker's history is their stored thread (``thread_history``), with the
    client's copy as the fallback. An intercept is finalized inside its
    own guard, exactly as the route did: a failure anywhere in it falls
    through to the next one."""
    question = question.strip()
    if screen:
        history = screen_history(history)
    elif user_id:
        history = thread_history(database, user_id, question, user_client_id) or history
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
