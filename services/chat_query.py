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

import copy
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


_CHAT_RESPONSE_META = "chat_response"
_CHAT_RESPONSE_VERSION = 1
_CHAT_TURN_META = "chat_turn"
_CHAT_TURN_VERSION = 1
_CHAT_TURN_PENDING = "pending"
_CHAT_TURN_COMPLETED = "completed"
_CHAT_TURN_FAILED = "failed"
_CHAT_RESPONSE_FIELDS = (
    "answer", "bubbles", "show_record_ui", "suggested_action",
    "suggested_actions", "app_action", "offer", "take_card",
    "row_metadata", "after_take", "persisted", "persisted_client_id",
    "request_id", "client_id", "terminal", "outcome", "retryable",
    "timeout", "failure",
)


def chat_turn_id(value=None) -> str:
    """Return one canonical UUID for a logical chat turn.

    A supplied UUID is the durable correlation key.  A missing key gets a
    fresh UUID rather than one derived from the words: two intentional
    ``"nice"`` messages are two turns, while a transport retry carries the
    original UUID.  The route echoes this value so a caller that needs retry
    safety can retain it.
    """
    if _is_uuid(value):
        return str(uuid.UUID(str(value)))
    return str(uuid.uuid4())


def is_chat_turn_id(value) -> bool:
    """Whether a supplied client/request id is a valid correlation UUID."""
    return _is_uuid(value)


def bot_client_id(user_client_id: str) -> str:
    """The one durable bot-row identity for a correlated user turn."""
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"willab-chat-bot:{user_client_id}"))


def _has_structured_intervention(resp: dict) -> bool:
    return any(resp.get(key) for key in (
        "suggested_action", "suggested_actions", "app_action", "offer",
        "take_card", "row_metadata",
    ))


def terminal_response(resp: dict, request_id: str, *, replayed: bool = False) -> dict:
    """Attach the additive terminal contract the chat UI can settle on.

    ``answer`` and the established card fields stay exactly where existing
    clients expect them.  The explicit fields mean the UI never has to infer
    completion from a delayed/stale bubble: every route result says which
    logical turn it belongs to, whether it is final, and whether retrying is
    safe.  A failure is intentionally structured rather than encoded in a
    generic acknowledgement.
    """
    failure = resp.get("failure")
    failure = failure if isinstance(failure, dict) else None
    if failure is not None:
        failure = {
            "code": str(failure.get("code") or "CHAT_RESPONSE_UNAVAILABLE"),
            "retryable": bool(failure.get("retryable", True)),
            "timeout": bool(failure.get("timeout", False)),
            **({"retry_after_ms": int(failure["retry_after_ms"])}
               if isinstance(failure.get("retry_after_ms"), int) else {}),
        }
        resp["failure"] = failure
    else:
        resp["failure"] = None
    resp["client_id"] = request_id
    resp["request_id"] = request_id
    resp["terminal"] = True
    resp["outcome"] = (
        "recoverable_error" if failure else
        ("structured" if _has_structured_intervention(resp) else "reply")
    )
    resp["retryable"] = bool(failure and failure["retryable"])
    resp["timeout"] = bool(failure and failure["timeout"])
    if replayed:
        resp["replayed"] = True
    return resp


def terminal_error_response(
    request_id: str, code: str, *, retryable: bool, timeout: bool = False,
    retry_after_ms: Optional[int] = None,
) -> dict:
    """A shape-complete, non-copy-bearing terminal error for the chat UI."""
    failure: dict[str, Any] = {
        "code": code,
        "retryable": retryable,
        "timeout": timeout,
    }
    if retry_after_ms is not None:
        failure["retry_after_ms"] = retry_after_ms
    return terminal_response({
        "answer": "", "bubbles": [], "show_record_ui": False,
        "suggested_action": None, "suggested_actions": None,
        "app_action": None, "failure": failure,
    }, request_id)


def _chat_response_receipt(resp: dict) -> dict:
    """The JSON-safe terminal payload kept beside the bot bubble for retry.

    The receipt deliberately contains response/UI metadata, not prompt
    context, private notes, or provider data.  It lets a retry replay the
    completed result without running intercepts, a model call, billing, or a
    walk-state transition again.
    """
    return {
        "version": _CHAT_RESPONSE_VERSION,
        "response": copy.deepcopy({
            key: resp[key] for key in _CHAT_RESPONSE_FIELDS if key in resp
        }),
    }


def _receipt_replay(metadata: Any, turn_id: str) -> Optional[dict]:
    """Return a terminal receipt stored on either row of a chat turn."""
    if not isinstance(metadata, dict):
        return None
    receipt = metadata.get(_CHAT_RESPONSE_META)
    cached = receipt.get("response") if isinstance(receipt, dict) else None
    if not isinstance(cached, dict):
        return None
    return terminal_response(copy.deepcopy(cached), turn_id, replayed=True)


def _turn_metadata(row: Any) -> tuple[dict, dict]:
    """Return the raw row metadata and its chat-turn subdocument safely."""
    metadata = row.get("metadata") if isinstance(row, dict) else None
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    turn = metadata.get(_CHAT_TURN_META)
    return metadata, dict(turn) if isinstance(turn, dict) else {}


def _read_lounge_row(database, user_id, client_id) -> Optional[dict]:
    getter = getattr(database, "get_lounge_message_by_client_id", None)
    if not callable(getter) or not user_id or not client_id:
        return None
    try:
        row = getter(str(user_id), str(client_id))
        return row if isinstance(row, dict) else None
    except Exception as error:  # noqa: BLE001 -- a retry can still answer
        logger.warning("chat/query: correlated turn unread user=%s: %s", user_id, error)
        return None


def replay_chat_turn(database, user_id, user_client_id, question: str) -> Optional[dict]:
    """Return a completed correlated turn without executing it again.

    This is intentionally called *before* the stateful feedback/Will
    intercepts.  Their writes happen before ordinary chat persistence, so a
    post-hoc UPSERT alone cannot make a retry safe.
    """
    if not (user_id and _is_uuid(user_client_id)):
        return None
    turn_id = chat_turn_id(user_client_id)
    mine = _read_lounge_row(database, user_id, turn_id)
    if mine and mine.get("chat_erased"):
        return terminal_error_response(turn_id, "CHAT_TURN_DELETED", retryable=False)
    user_replay = None
    if mine and mine.get("role") == "user":
        stored_question = str(mine.get("body") or "").strip()
        if stored_question and stored_question != (question or "").strip():
            return terminal_error_response(
                turn_id, "CHAT_TURN_CONFLICT", retryable=False,
            )
        user_replay = _receipt_replay((mine.get("metadata") or {}), turn_id)
    row = _read_lounge_row(database, user_id, bot_client_id(turn_id))
    if row and row.get("role") == "bot":
        if row.get("chat_erased"):
            return terminal_error_response(turn_id, "CHAT_TURN_DELETED", retryable=False)
        metadata = row.get("metadata") or {}
        replay = _receipt_replay(metadata, turn_id)
        if replay is not None:
            # A committed bot response is authoritative over a stale failure
            # receipt on the user row (for example, a network response lost
            # after the database accepted the bot write).
            return replay
    if user_replay is not None:
        return user_replay
    if not row or row.get("role") != "bot":
        return None
    metadata = row.get("metadata") or {}

    # Rows written before the response-receipt contract remain safe to replay:
    # use their actual conversational bubble and the structured fields that
    # were already persisted, never regenerate a potentially different reply.
    from services.master_doc_rag import split_answer_into_bubbles
    answer = str(row.get("body") or "")
    legacy = {
        "answer": answer,
        "bubbles": metadata.get("bubbles") or split_answer_into_bubbles(answer),
        "show_record_ui": False,
        "suggested_action": metadata.get("suggested_action"),
        "suggested_actions": metadata.get("suggested_actions"),
        "app_action": metadata.get("app_action"),
        "persisted": True,
        "persisted_client_id": str(row.get("client_id") or bot_client_id(turn_id)),
    }
    return terminal_response(legacy, turn_id, replayed=True)


def _chat_scope(place, scope_metadata=None) -> dict:
    from services.lounge_messages import PLACES
    return {**(scope_metadata or {}),
            **({"place": place} if place in PLACES else {})}


def claim_chat_turn(database, user_id, turn_id: str, question: str, *,
                    user_created_at=None, place=None,
                    scope_metadata=None) -> tuple[Optional[str], Optional[dict]]:
    """Atomically reserve a persisted chat turn before it can change state.

    ``lounge_messages`` already has the owner-scoped unique key we need.  A
    one-row, ``ignore_duplicates`` write puts a random claim token beside the
    user's message.  The process whose token survived owns the turn; another
    transport attempt must replay its receipt (or report that it is still in
    progress) and never rerun an intercept, model call, charge or Take
    release.  This keeps the receipt protocol migration-free while using the
    database, rather than an in-process lock, as the arbitration point.
    """
    if not (user_id and _is_uuid(turn_id)):
        return None, terminal_error_response(
            chat_turn_id(turn_id), "CHAT_PERSIST_FAILED", retryable=True,
        )
    replay = replay_chat_turn(database, user_id, turn_id, question)
    if replay is not None:
        return None, replay

    stamp = _chat_scope(place, scope_metadata)
    claim_id = str(uuid.uuid4())
    q = (question or "").strip()
    created_at = (
        user_created_at if isinstance(user_created_at, str)
        and user_created_at.strip() else datetime.now(timezone.utc).isoformat()
    )
    pending = {
        "client_id": turn_id, "role": "user", "kind": "text", "body": q,
        "metadata": {
            **stamp,
            _CHAT_TURN_META: {
                "version": _CHAT_TURN_VERSION,
                "state": _CHAT_TURN_PENDING,
                "claim_id": claim_id,
            },
        },
        "client_created_at": created_at,
    }
    claim = getattr(database, "claim_lounge_chat_turn", None)
    try:
        if callable(claim):
            stored = claim(str(user_id), pending)
        else:  # narrow compatibility seam for older test/database adapters
            rows = database.insert_lounge_messages(str(user_id), [pending]) or []
            stored = next((row for row in rows if isinstance(row, dict)
                           and str(row.get("client_id") or "") == turn_id), None)
        stored = stored or _read_lounge_row(database, user_id, turn_id)
    except Exception as error:  # noqa: BLE001 -- the UI gets a terminal retry state
        logger.warning("chat/query: turn claim failed user=%s: %s", user_id, error)
        stored = None
    if not stored:
        return None, terminal_error_response(
            turn_id, "CHAT_PERSIST_FAILED", retryable=True,
        )
    if stored.get("role") != "user" or stored.get("kind") != "text":
        return None, terminal_error_response(
            turn_id, "CHAT_TURN_CONFLICT", retryable=False,
        )
    stored_question = str(stored.get("body") or "").strip()
    if stored_question != q:
        return None, terminal_error_response(
            turn_id, "CHAT_TURN_CONFLICT", retryable=False,
        )
    _metadata, stored_turn = _turn_metadata(stored)
    if (stored_turn.get("state") == _CHAT_TURN_PENDING
            and stored_turn.get("claim_id") == claim_id):
        return claim_id, None

    replay = replay_chat_turn(database, user_id, turn_id, question)
    if replay is not None:
        return None, replay
    code = ("CHAT_TURN_IN_PROGRESS" if stored_turn.get("state") == _CHAT_TURN_PENDING
            else "CHAT_TURN_UNAVAILABLE")
    return None, terminal_error_response(
        turn_id, code, retryable=True, retry_after_ms=1000,
    )


def _claim_is_owned(database, user_id, turn_id: str, claim_id: Optional[str]) -> bool:
    """Whether this process still owns the pending durable turn."""
    if not claim_id:
        return True
    row = _read_lounge_row(database, user_id, turn_id)
    _metadata, turn = _turn_metadata(row)
    return (turn.get("state") == _CHAT_TURN_PENDING
            and turn.get("claim_id") == claim_id)


def complete_chat_turn_claim(database, user_id, turn_id: str, claim_id: Optional[str], *,
                             state: str, response: Optional[dict] = None) -> bool:
    """Mark a claim completed/failed and, on failure, retain its terminal receipt.

    The successful response stays beside the bot bubble.  If writing that
    bubble failed after an intercept had changed state, the user row holds the
    terminal error receipt instead; a retry replays it rather than executing
    the intercept a second time.
    """
    if not claim_id or state not in (_CHAT_TURN_COMPLETED, _CHAT_TURN_FAILED):
        return False
    row = _read_lounge_row(database, user_id, turn_id)
    rewrite = getattr(database, "rewrite_lounge_message", None)
    if not row:
        return False
    metadata, turn = _turn_metadata(row)
    if (turn.get("claim_id") != claim_id
            or turn.get("state") != _CHAT_TURN_PENDING):
        return False
    turn["state"] = state
    metadata[_CHAT_TURN_META] = turn
    if response is not None:
        metadata[_CHAT_RESPONSE_META] = _chat_response_receipt(response)
    complete = getattr(database, "complete_lounge_chat_turn", None)
    if callable(complete):
        try:
            return bool(complete(str(user_id), turn_id, str(claim_id), metadata))
        except Exception as error:  # noqa: BLE001 -- the route still returns its terminal result
            logger.warning("chat/query: turn claim completion failed user=%s: %s",
                           user_id, error)
            return False
    if not callable(rewrite):
        return False
    try:
        written = rewrite(str(user_id), turn_id, str(row.get("body") or ""), metadata)
        return bool(written)
    except Exception as error:  # noqa: BLE001 -- the route still returns its terminal result
        logger.warning("chat/query: turn claim completion failed user=%s: %s",
                       user_id, error)
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
                  bubbles, app_action=None, response_receipt=None,
                  claim_id=None, extra=None) -> dict:
    meta: dict[str, Any] = {**(extra or {}), "intent": intent}
    if suggested_action:
        meta["suggested_action"] = suggested_action
    if suggested_actions:
        meta["suggested_actions"] = suggested_actions
    if bubbles:
        meta["bubbles"] = bubbles
    if app_action:
        meta["app_action"] = app_action
    if response_receipt:
        meta[_CHAT_RESPONSE_META] = response_receipt
    if claim_id:
        meta[_CHAT_TURN_META] = {
            "version": _CHAT_TURN_VERSION,
            "claim_id": str(claim_id),
        }
    return meta


def _chat_turn_rows(
    database, user_id, question, answer, *, suggested_action=None,
    suggested_actions=None, bubbles=None, intent=None,
    user_client_id=None, user_created_at=None, offer=None, take_card=None,
    row_metadata=None, app_action=None, response_receipt=None,
    claim_id=None, bot_row=True, place=None, scope_metadata=None,
) -> tuple[str, list[dict]]:
    """Build the stable user/bot rows and their deterministic bot identity."""
    stamp = _chat_scope(place, scope_metadata)
    q = (question or "").strip()
    u_id = chat_turn_id(user_client_id)
    b_id = bot_client_id(u_id)
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
            "metadata": {
                **stamp,
                **({"arc_id": row_metadata["arc_id"],
                    "take_session_id": row_metadata.get("take_session_id"),
                    "will_question_step": "answer"}
                   if (row_metadata or {}).get("offer") == "will_question"
                   and row_metadata.get("arc_id") else {}),
            } or None,
        })
    if bot_row:
        rows.append({
            "client_id": b_id, "role": "bot", "kind": "text", "body": answer,
            "metadata": {**(_bot_metadata(
                intent=intent, suggested_action=suggested_action,
                suggested_actions=suggested_actions, bubbles=bubbles,
                app_action=app_action, response_receipt=response_receipt,
                claim_id=claim_id,
                extra=row_metadata) or {}), **stamp,
                         "reply_to_client_id": u_id},
            "client_created_at": now_iso,
        })
    if offer:
        rows.append(_offer_row(b_id, offer, stamp_after(now_iso)))
    if take_card:
        rows.append(_take_card_row(b_id, take_card, stamp_after(now_iso, gap_ms=2)))
    return b_id, rows


def _persisted_bot_is_ours(database, user_id, rows: list[dict], bot_id: str,
                            *, claim_id=None, bot_row=True) -> bool:
    """Confirm a bot receipt reached storage and belongs to this claim."""
    try:
        persisted = database.insert_lounge_messages(str(user_id), rows) or []
    except Exception as error:
        # The write may have reached the database even when its response did
        # not reach us.  Read the deterministic bot id once before recording a
        # failed receipt, otherwise a valid answer could be poisoned as a
        # failure and replayed forever.
        logger.warning("chat/query: persist turn failed user=%s: %s", user_id, error)
        persisted = []
    bot = next((row for row in persisted if isinstance(row, dict)
                and str(row.get("client_id") or "") == bot_id), None)
    bot = bot or _read_lounge_row(database, user_id, bot_id)
    # A DB wrapper may absorb a write error and return [], so only claim
    # success when the actual bot receipt is present.  A claim-aware write
    # must additionally read back its own random claim id: a duplicate bot
    # row belonging to another process is replayable, never permission to
    # charge or release a Take a second time.
    bot_meta = bot.get("metadata") if isinstance(bot, dict) else None
    bot_turn = bot_meta.get(_CHAT_TURN_META) if isinstance(bot_meta, dict) else None
    is_bot_row = isinstance(bot, dict) and bot.get("role") == "bot"
    own_claim = (not claim_id or (isinstance(bot_turn, dict)
                                  and bot_turn.get("claim_id") == claim_id))
    return bool(bot_row and is_bot_row and own_claim)


def persist_chat_turn(
    database, user_id, question, answer, *, suggested_action=None,
    suggested_actions=None, bubbles=None, intent=None,
    user_client_id=None, user_created_at=None, offer=None, take_card=None,
    row_metadata=None, app_action=None, response_receipt=None,
    claim_id=None, bot_row=True, place=None, scope_metadata=None,
):
    """Persist a Lounge turn and return its confirmed bot identity.

    The client/request UUID is the user-turn id and the bot row derives from
    it, so a repost is a no-op at the existing ``(user_id, client_id)`` key.
    Missing IDs are deliberately fresh rather than derived from the words.
    """
    answer = (answer or "").strip()
    if not user_id or not answer:
        return None
    bot_id, rows = _chat_turn_rows(
        database, user_id, question, answer,
        suggested_action=suggested_action, suggested_actions=suggested_actions,
        bubbles=bubbles, intent=intent, user_client_id=user_client_id,
        user_created_at=user_created_at, offer=offer, take_card=take_card,
        row_metadata=row_metadata, app_action=app_action,
        response_receipt=response_receipt, claim_id=claim_id,
        bot_row=bot_row, place=place, scope_metadata=scope_metadata,
    )
    return (bot_id if _persisted_bot_is_ours(
        database, user_id, rows, bot_id, claim_id=claim_id, bot_row=bot_row,
    ) else None)


def _control_after_note(database, user_id) -> bool:
    """Under a note: the sales question for a sale that stalled, else Will's
    answer to a worry (N241 O1, P2), then what the note says of a strength
    (N2, N3); never in the way of the note."""
    try:
        from services.sales_framing import answers_after_note
        from services.strengths import after_note as strengths_after_note
        rows = answers_after_note(database, str(user_id))
        try:
            rows = rows + strengths_after_note(database, str(user_id))
        except Exception as e:  # noqa: BLE001 -- the note is kept either way
            logger.warning("chat/query: strengths read failed user=%s: %s", user_id, e)
        return bool(rows)
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("chat/query: worry answer failed user=%s: %s", user_id, e)
        return False


def _after_note(database, user_id) -> bool:
    """Under a # note's "Noted.", in order: the privacy line on every fifth
    note that names someone (N411 item 3), the ask for life goals (N172 M1),
    then the sales question or Will's answer to a worry (N241 O1, P2). True
    when any of them wrote: the Lounge reads the thread again."""
    wrote = _privacy_after_note(database, user_id)
    wrote = _goals_after_note(database, user_id) or wrote
    return _control_after_note(database, user_id) or wrote


def _privacy_after_note(database, user_id) -> bool:
    try:
        from services.voice_notebook import privacy_after_note
        return bool(privacy_after_note(database, str(user_id)))
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("chat/query: privacy reminder failed user=%s: %s", user_id, e)
        return False


def _goals_after_note(database, user_id) -> bool:
    try:
        from services.life_goals import after_note
        return bool(after_note(database, str(user_id)))
    except Exception as e:  # noqa: BLE001 -- the note is kept either way
        logger.warning("chat/query: life goals ask failed user=%s: %s", user_id, e)
        return False


def _write_chat_response_receipt(database, user_id, bot_cid, resp: dict) -> None:
    """Refresh the receipt after post-persist walk work has settled.

    The initial receipt is written in the same batch as the bot bubble.  A
    Take settlement can then append/release rows, so the persisted receipt is
    refreshed in place with the final client-visible contract.  Failure here
    is non-fatal: the original bubble and response remain valid.
    """
    row = _read_lounge_row(database, user_id, bot_cid)
    rewrite = getattr(database, "rewrite_lounge_message", None)
    if not row or not callable(rewrite):
        return
    try:
        metadata = dict(row.get("metadata") or {})
        metadata[_CHAT_RESPONSE_META] = _chat_response_receipt(resp)
        rewrite(str(user_id), str(bot_cid), str(row.get("body") or ""), metadata)
    except Exception as error:  # noqa: BLE001 -- the completed turn is kept
        logger.warning("chat/query: response receipt refresh failed user=%s: %s",
                       user_id, error)


def _post_persist_effects(database, user_id, resp: dict, intent: Optional[str]) -> None:
    """Run nonessential follow-on work without changing a saved turn's outcome.

    Once the bot row and its initial receipt exist, that response is the
    durable terminal result for the correlation id.  A later walk/note action
    is useful, but it must not turn the first HTTP response into an error that
    a retry then contradicts by replaying the saved success.
    """
    from services import after_take

    try:
        # ``settled_take`` only accepts an answer to the open question that
        # owns this Take.  It replaces the old unscoped release which could
        # release stale terminal state below an unrelated message.
        settled_take = after_take.settled_take(resp)
        if (intent != "crisis" and settled_take
                and after_take.release(database, user_id, take=settled_take)):
            resp["after_take"] = True
    except Exception as error:  # noqa: BLE001 -- saved reply remains terminal
        logger.warning("chat/query: after-take follow-on failed user=%s: %s",
                       user_id, error)

    # The case is a server-only instruction for the follow-on writer; do not
    # let it leak into the returned/replayed chat contract.
    case = resp.pop("sunday_case", None)
    if intent == "sunday_note" and case:
        try:
            from services.sunday_note import after_head
            if after_head(database, user_id, case):
                resp["after_take"] = True
        except Exception as error:  # noqa: BLE001 -- saved reply remains terminal
            logger.warning("chat/query: sunday-note follow-on failed user=%s: %s",
                           user_id, error)

    if (intent == "voice_notebook"
            and (resp.get("row_metadata") or {}).get("voice_note")):
        try:
            if _after_note(database, user_id):
                resp["after_take"] = True
        except Exception as error:  # noqa: BLE001 -- saved reply remains terminal
            logger.warning("chat/query: voice-note follow-on failed user=%s: %s",
                           user_id, error)


def finish_chat_turn(database, resp: dict, *, user_id, question,
                     persist_thread, user_client_id, user_created_at,
                     intent=None, place=None, request_id=None,
                     claim_id=None, scope_metadata=None) -> dict:
    """Persist and charge one completed turn; return one terminal outcome.

    Only a reply that explicitly settles the *same* Take may advance an
    after-Take chain.  A normal later FAQ must never release a held closing
    message and make ``Good job. See you next time.`` appear as its answer.
    """
    turn_id = chat_turn_id(request_id or user_client_id)
    terminal_response(resp, turn_id)
    persisted_turn = False
    bot_cid = None
    if (persist_thread and user_id and claim_id
            and not _claim_is_owned(database, user_id, turn_id, claim_id)):
        replay = replay_chat_turn(database, user_id, turn_id, question)
        if replay is not None:
            return replay
        return terminal_error_response(
            turn_id, "CHAT_TURN_IN_PROGRESS", retryable=True,
            retry_after_ms=1000,
        )
    if persist_thread and user_id:
        # The receipt is initially written with the reply.  Its final fields
        # are refreshed after the narrowly correlated walk transition below.
        expected_bot_cid = bot_client_id(turn_id)
        resp["persisted"] = True
        resp["persisted_client_id"] = expected_bot_cid
        bot_cid = persist_chat_turn(
            database, user_id, question, resp.get("answer"),
            suggested_action=resp.get("suggested_action"),
            suggested_actions=resp.get("suggested_actions"),
            bubbles=resp.get("bubbles"), intent=intent,
            user_client_id=turn_id, user_created_at=user_created_at,
            offer=resp.get("offer"), take_card=resp.get("take_card"),
            row_metadata=resp.get("row_metadata"),
            app_action=resp.get("app_action"),
            response_receipt=_chat_response_receipt(resp), claim_id=claim_id,
            place=place, scope_metadata=scope_metadata,
        )
        persisted_turn = bool(bot_cid)
        resp["persisted"] = persisted_turn
        if bot_cid:
            resp["persisted_client_id"] = bot_cid
        else:
            resp.pop("persisted_client_id", None)
            resp["failure"] = {
                "code": "CHAT_PERSIST_FAILED", "retryable": True,
                "timeout": False,
            }
            terminal_response(resp, turn_id)
            complete_chat_turn_claim(
                database, user_id, turn_id, claim_id,
                state=_CHAT_TURN_FAILED, response=resp,
            )

        if bot_cid:
            _post_persist_effects(database, user_id, resp, intent)
            terminal_response(resp, turn_id)
            _write_chat_response_receipt(database, user_id, bot_cid, resp)
            complete_chat_turn_claim(
                database, user_id, turn_id, claim_id,
                state=_CHAT_TURN_COMPLETED,
            )
    # A durable retry is charged once: only the successful original write can
    # reach this point.  An explicit persistence failure is not charged and
    # does not move a Take chain.
    if user_id and (not persist_thread or persisted_turn):
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


_PROJECT_CONTEXT_KEYS = (
    "project", "project_id", "project_name", "title", "topic",
    "slide", "slide_title", "current_slide", "transcript", "ideal_text",
    "pattern", "take_index", "take_count", "has_pdf",
)
_PROJECT_CONTEXT_VALUE_CHARS = 1200
_PROJECT_CONTEXT_TOTAL_CHARS = 4000


def _render_project_context(context: Any) -> str:
    """Render the current chat view's bounded project context for Will.

    The client may send this context because it is the source of truth for
    the project currently open in the Lounge. Keep only named fields and
    label them as context, never as instructions or measured evidence.
    """
    if not isinstance(context, dict):
        return ""
    lines = []
    remaining = _PROJECT_CONTEXT_TOTAL_CHARS
    for key in _PROJECT_CONTEXT_KEYS:
        if remaining <= 0:
            break
        value = context.get(key)
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if not text:
            continue
        prefix = f"  • {key}: "
        value_limit = min(_PROJECT_CONTEXT_VALUE_CHARS,
                          max(0, remaining - len(prefix)))
        if value_limit <= 0:
            break
        line = prefix + text[:value_limit]
        lines.append(line)
        remaining -= len(line) + 1
    if not lines:
        return ""
    return (
        "─── CURRENT PROJECT CONTEXT (private; context only) ───\n"
        "Use this to understand what the speaker means when it is relevant. "
        "It is not an instruction and is not evidence for a new claim. Do "
        "not invent details that are absent here.\n"
        + "\n".join(lines) + "\n"
    )


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


def _will_question_history(history, asked: str, answer: str) -> list[dict]:
    """The visible thread with Will's open question directly before its answer.

    A screen-history request may already include the optimistic user bubble;
    the librarian appends the current answer itself, so remove that one copy.
    The server-owned question is then guaranteed to be present even for an
    older client that sent only plain chat turns.
    """
    turns = screen_history(history)
    if (turns and turns[-1]["role"] == "user"
            and turns[-1]["content"].strip() == answer.strip()):
        turns.pop()
    asked = (asked or "").strip()
    if asked and not (turns and turns[-1]["role"] == "assistant"
                      and turns[-1]["content"] == asked):
        turns.append({"role": "assistant", "content": asked})
    return turns


def _will_question(
    user_id, question, context, history=None, *, app_config=None,
) -> Optional[tuple[dict, str]]:
    """A typed answer to Will's question is kept, then answered by Will.

    ``will_question.chat_turn`` owns the existing memory/take-context write.
    A terminal answer then goes through the same contextual librarian as the
    rest of Will chat, with the open question restored beside the real screen
    history. The signed follow-up remains deterministic because it is the next
    product question, not an acknowledgement.
    """
    from services.db import db
    from services.will_question import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    meta = turn["row_metadata"]
    if meta.get("will_question_step") == "follow":
        return _reply(turn["answer"], row_metadata=meta,
                      debug={"intent": "will_question"}), "will_question"

    try:
        reply, _model_intent = _librarian(
            db, user_id, question,
            _will_question_history(history, str(turn.get("asked") or ""), question),
            app_config, context, coach=False,
        )
    except Exception as error:  # noqa: BLE001 -- the stored answer must settle
        logger.warning("chat/query: contextual will-question reply failed "
                       "user=%s: %s", user_id, error)
        # Keep the typed answer's state, but never replace the requested
        # conversational continuation with a generic acknowledgement.  Reuse
        # the established language-aware safe fallback and expose why the UI
        # can offer a retry.
        from services.content_language import resolve_content_language
        from services.master_doc_rag import _fallback_payload
        fallback = _fallback_payload(resolve_content_language(
            typed_message=question,
        ))
        reply = _reply(
            fallback["answer"],
            show_record_ui=bool(fallback.get("show_record_ui")),
            suggested_action=fallback.get("suggested_action"),
            app_action=fallback.get("app_action"),
            failure={
                "code": "CHAT_CONTEXT_UNAVAILABLE", "retryable": True,
                "timeout": False,
            },
        )
    reply["row_metadata"] = meta
    reply["debug"] = {**(reply.get("debug") or {}), "intent": "will_question"}
    return reply, "will_question"


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


def _your_why(user_id, question, _context, _history=None) -> Optional[tuple[dict, str]]:
    """Their why asked for in their own words (N255 Q3): the lens opens,
    because they asked."""
    from services.db import db
    from services.your_why import chat_turn
    turn = chat_turn(db, user_id, question)
    if not turn:
        return None
    return _reply(turn["answer"], row_metadata=turn["row_metadata"],
                  debug={"intent": "your_why"}), "your_why"


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


def _intercepts(user_id, app_config, *, ordinary_coach=False) -> list[tuple[str, Callable]]:
    life_on = bool(user_id and getattr(app_config, "LIFE_PANEL_ENABLED", False))
    audit_on = bool(user_id and getattr(app_config, "AUDIT_SURFACE_ENABLED", False))
    chain: list[tuple[str, Callable]] = []
    if user_id:
        if not ordinary_coach:
            chain.append(("feedback-check intercept failed user=%s: %s", _feedback_check))
            chain.append(("will-question intercept failed user=%s: %s",
                          functools.partial(_will_question, app_config=app_config)))
        chain.append(("whatsapp-number intercept failed user=%s: %s", _whatsapp_number))
        chain.append(("sunday-note intercept failed user=%s: %s", _sunday_note))
        chain.append(("life-goals intercept failed user=%s: %s", _life_goals))
        chain.append(("your-why intercept failed user=%s: %s", _your_why))
        chain.append(("voice-notebook intercept failed user=%s: %s", _voice_notebook))
    if life_on:
        chain.append(("life-panel intercept failed user=%s: %s", _life_panel))
    if user_id:
        chain.append(("goal-update intercept failed user=%s: %s", _goal_update))
    if audit_on:
        chain.append(("audit intercept failed user=%s: %s", _audit))
    chain.append(("presentation-change intercept failed: %s", _presentation_change))
    if not ordinary_coach:
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


def _failure_from_debug(debug: Any) -> Optional[dict]:
    """Map model/fallback diagnostics to a stable frontend-safe failure.

    The human-facing fallback remains the approved safe text; exception
    details stay in logs/debug and never enter the response contract.
    """
    if not isinstance(debug, dict) or not debug.get("error"):
        return None
    error = str(debug.get("error") or "")
    timeout = error == "llm_timeout" or "timeout" in error.lower()
    codes = {
        "llm_timeout": "CHAT_MODEL_TIMEOUT",
        "llm_unavailable": "CHAT_MODEL_UNAVAILABLE",
        "llm_error": "CHAT_MODEL_UNAVAILABLE",
        "empty_response": "CHAT_MODEL_EMPTY_RESPONSE",
        "parse_error": "CHAT_MODEL_INVALID_RESPONSE",
        "empty_answer": "CHAT_MODEL_EMPTY_RESPONSE",
        "output_language": "CHAT_MODEL_LANGUAGE_REJECTED",
    }
    return {
        "code": "CHAT_MODEL_TIMEOUT" if timeout else
                codes.get(error, "CHAT_RESPONSE_UNAVAILABLE"),
        "retryable": True,
        "timeout": timeout,
    }


def _librarian(database, user_id, question, history, app_config,
               context=None, *, coach=True) -> tuple[dict, str]:
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
    from services import speaking_coach
    coach_reply = coach and speaking_coach.answer(
        database, user_id, question, history=history, app_config=app_config,
    )
    if coach_reply:
        payload, debug = coach_reply
        row_metadata = payload.get("row_metadata")
        extra = {"row_metadata": row_metadata} if row_metadata else {}
        return _reply(payload["answer"], debug=debug, **extra), "speaking_coach"
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
                             "memory": memory(),
                             "context": _render_project_context(context)})
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
    if action:
        extra["app_action"] = action
    failure = _failure_from_debug(debug)
    if failure:
        extra["failure"] = failure
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
    """The rows the Lounge hides (frontend isRetiredLoungeMessage). The
    founder's weekly note is retired too (N516): no longer written, and the
    ones already in the chat are never read back to Will."""
    meta = row.get("metadata") or {}
    return (row.get("kind") == "cadence" and meta.get("beat") == 0) or \
        meta.get("note") in ("human_check", "coach_video_shared", "feedback_digest")


def _project_message(row: dict) -> bool:
    """Whether a conversation row belongs to one project's chat."""
    meta = row.get("metadata") or row.get("meta") or {}
    return any(
        isinstance(meta.get(key), str) and bool(meta[key].strip())
        for key in ("arc_id", "project_id", "projectId")
    )


def _walk_terminal_message(role: Any, content: Any, metadata: Any = None) -> bool:
    """Whether a rendered assistant bubble is a completed walk closing.

    Closing rows are UI state for the completed Take, never conversational
    context for a later question.  Metadata is authoritative for stored rows;
    the exact approved closing text protects older screen-history clients
    that only send role/content.
    """
    if role != "assistant" or not isinstance(content, str):
        return False
    meta = metadata if isinstance(metadata, dict) else {}
    if meta.get("next_take") is True:
        return True
    from services.after_take import SEE_YOU, SEE_YOU_ON
    text = content.strip()
    if text == SEE_YOU:
        return True
    prefix, suffix = SEE_YOU_ON.split("{day}")
    return text.startswith(prefix) and text.endswith(suffix) and len(text) > len(prefix) + len(suffix)


def _fallback_label(row: dict) -> str:
    """The signed fallback after a Take, told to Will as such (founder
    2026-10-20), so he knows the written summary's specifics are missing;
    the frontend's screen copy says the same. Empty for any other row."""
    meta = row.get("metadata") or {}
    if not (meta.get("summary") is True and meta.get("written") is False):
        return ""
    take = meta.get("take_index")
    which = f"Take {take}" if isinstance(take, int) else "this Take"
    if meta.get("writing"):  # GPT-4o's summary is still being written (WILL-07)
        return f"[The app's fixed message after {which}; the written summary is not in yet]\n"
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
        role = "user" if row.get("role") == "user" else "assistant"
        if (row.get("role") not in ("user", "bot") or not body
                or row.get("kind") not in _HISTORY_KINDS or _retired(row)
                or _project_message(row)
                or _walk_terminal_message(role, body, row.get("metadata"))
                or (user_client_id and row.get("client_id") == user_client_id)):
            continue
        turns.append({"role": role,
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
        if _project_message(m):
            continue
        content = m.get("content")
        if isinstance(content, str) and content.strip():
            if _walk_terminal_message(
                m["role"], content,
                m.get("metadata") if isinstance(m.get("metadata"), dict)
                else m.get("meta"),
            ):
                continue
            turns.append({"role": m["role"], "content": content.strip()[:_SCREEN_CHARS]})
    return turns[-_SCREEN_ROWS:]


def answer_chat(database, *, user_id, question: str, history, context,
                app_config, finalize: Callable[[dict, str], Any],
                user_client_id=None, screen: bool = False,
                project_id=None, take_id=None, place=None) -> Any:
    """Answer one turn and hand it to ``finalize(response, intent)``.

    ``screen``: the client sent the thread as the Lounge draws it
    (``screen_history``), which is what Will reads. Otherwise a signed-in
    speaker's history is their stored thread (``thread_history``), with the
    client's copy as the fallback. An intercept is finalized inside its
    own guard, exactly as the route did: a failure anywhere in it falls
    through to the next one."""
    question = question.strip()
    if project_id and user_id:
        from services import project_chat
        from services.chat_intents import detect_chat_intent
        safety = detect_chat_intent(question)
        if safety and safety.get("intent") == "crisis":
            claimed = _chat_intent(user_id, question, context, history)
            if claimed:
                return finalize(*claimed)
        focus = context.get("review_focus") if isinstance(context, dict) else None
        live_feedback = isinstance(context, dict) and context.get("live_take_feedback") is True
        return finalize(*project_chat.answer(
            database, str(user_id), str(project_id), question,
            take_session_id=take_id,
            **({"review_focus": focus} if focus is not None else {}),
            **({"live_take_feedback": True} if live_feedback else {}),
        ))
    if screen:
        history = screen_history(history)
    elif user_id:
        history = thread_history(database, user_id, question, user_client_id) or history
    ordinary_coach = place == "speaking" and bool(
        getattr(app_config, "SPEAKING_COACH_ENABLED", False))
    if ordinary_coach:
        from services.chat_intents import detect_chat_intent
        safety = detect_chat_intent(question)
        if safety and safety.get("intent") == "crisis":
            claimed = _chat_intent(user_id, question, context, history)
            if claimed:
                return finalize(*claimed)
    for failure, intercept in _intercepts(user_id, app_config, ordinary_coach=ordinary_coach):
        try:
            claimed = intercept(user_id, question, context, history)
            if claimed:
                return finalize(*claimed)
        except Exception as error:
            args = (user_id, error) if "user=%s" in failure else (error,)
            logger.warning("chat/query: " + failure, *args)
    return finalize(*_librarian(database, user_id, question, history,
                                app_config, context, coach=ordinary_coach))
