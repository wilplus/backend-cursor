"""One action at a time after a Take, in a chain (founder 2026-10-20, N89,
after checking the app; the first form, one ask per Take, the same
morning).

After the Feedback walk the Lounge shows the Take's card and the summary
(``take_summary``): what the Take showed, with no next step and no record
button. Then, one at a time, each after the one before is answered: every
ask that waits, each opened by Will's lead-in line and followed by the
ask's buttons; and only then the closing message (``NEXT_TAKE``) with
"Record Take N" under it. The closing message is written with the summary's
batch but held back (``metadata.held_for`` names the ask in front of the
speaker, ``metadata.chain`` the asks still to come) and advances under
whatever closed the ask (``release``). The asks (``chain``), in order:

  Take 1      WhatsApp, while there is no number and it was asked fewer
              than twice (founder 2026-10-26, N171: the Take has gone to
              the coach, as every spoken Take does once it is processed,
              so the speaker has a reply to wait for); Will's question
              when it has one (``will_question``); "Did this help?" when
              the Take looks off (``feedback_check.looks_off``). Never an
              ask from the CEO panel, never the home screen.
  Take 2 on   the founder's ask from the CEO panel when one is open
              ("admin"; the Lounge draws it, and "Not now" leaves it open,
              so it comes back at the end of the next Take); WhatsApp, as
              above; the home screen, once, where the phone can add it;
              then Will's question when it has one; then "Did this help?"
              when the Take looks off.

One ask a Take (founder 2026-10-26, N189): the first that waits, in the
order above; the others wait for a later Take. So Take 1 brings the
WhatsApp ask and Take 2 the home screen. Was at most two (N94).

Will's question opens with a bridge line in the chat (``BRIDGE``, founder
2026-10-21, N94), between the summary and the question: two signed lines,
one a Take in turn. Only the chat has it, never the walk.

Will's lead-in (``will_question.lead_in``, started beside the summary's
own call and under the Take's authority): one or two sentences tied to
this Take before the ask's signed words said with a light touch, for
WhatsApp, the home screen and "Did this help?" (``LEAD_IN_ASKS``). Will's
own question needs none, and the CEO panel's asks are drawn as written
(their prices carry numbers; the data question's words belong to the
consent screen). A lead-in that fails its checks, or came too late, means
the ask as written.

Advancing (``release``), always under the rows that closed the ask:
  - "Yes" to "Did this help?": ``GLAD`` as the reply, then the next ask;
    "Skip", or the answer to "What would help?": under "Thanks!"
    (``feedback_check``);
  - Will's question answered (a tap with no follow-up, Skip, or typed
    words), as written (``will_question``);
  - a typed turn that passes the ask, under Will's reply
    (``chat_query.finish_chat_turn``); never under the chat's safety reply:
    after a distressed message the asks wait until the speaker writes
    again (founder 2026-10-21, N94);
  - the ask's form closing in the Lounge, whatever the choice (Save, Not
    now, See prices): POST /v2/user/lounge/after-take;
  - a newer Take's summary: an older held message is let go where it stands.
An ask that no longer applies when its turn comes (a number saved since) is
skipped. When the chain is empty the plan's lines after the Take are written
(``plan_flow.after_take``, "That's your 15 minutes for today."), then the
closing message is let go under the newest row, and the Lounge puts "Record
Take N" under it. Written with the summary, the plan's lines landed over
Will's question: its answers went and the closing message came at once.

Nothing here blocks the next Take: one tap on each ask (Not now, Skip, No)
brings the next, and the closing message after the last; the Ideal Text
page's own "Record Take N" is never held. No number, score or verdict, and
the only words are the founder's (``GLAD``, ``NEXT_TAKE``, 2026-10-20).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("9a3e6c1d-52b7-4f08-8d41-c7e2b05f9a63")

#: The founder's sentence after "Yes" (decisions page, 2026-10-20).
GLAD = "We're glad it helped you."
#: The closing message, once every ask is answered (founder 2026-10-20,
#: N89); the Lounge puts "Record Take N" under it.
NEXT_TAKE = "Look, practice makes perfect. If you're ready, let's go with the next take. 💪"
#: Asks the Lounge draws from the summary's batch as offer bubbles.
_OFFER_ASKS = ("whatsapp", "install")
#: The asks Will opens with a lead-in line (``will_question.lead_in``).
LEAD_IN_ASKS = ("whatsapp", "install", "feedback_check")
#: WhatsApp is asked at most this many times (founder 2026-10-20).
_WHATSAPP_TIMES = 2
#: At most this many asks after a Take (founder 2026-10-26, N189; was two,
#: N94).
_MOST = 1
#: Between the summary and Will's question, one a Take in turn (founder
#: 2026-10-21, N94: chosen in chat from four, "and variations of it").
BRIDGE = (
    "Ok, now let's dive into the content for a bit.",
    "Alright, let's dive into the content for a moment.",
)
#: How far back the thread is read for a held message and for earlier asks.
_LOOK = 60
_SCAN = 500


def _rows(database: Any, user_id: str, limit: int) -> list[dict]:
    try:
        return database.get_lounge_messages_page(str(user_id), limit=limit) or []
    except Exception as error:  # noqa: BLE001 -- an unread thread holds nothing
        logger.warning("after take: thread unread user=%s: %s", user_id, error)
        return []


def asked(database: Any, user_id: str, offer: str) -> int:
    """How many times this offer was asked in the thread."""
    return sum(1 for r in _rows(database, user_id, _SCAN)
               if (r.get("metadata") or {}).get("offer") == offer)


def _admin_ask(user_id: str) -> bool:
    try:
        from services import person_asks
        return person_asks.next_for(str(user_id)) is not None
    except Exception as error:  # noqa: BLE001 -- no ask read: the app's own asks
        logger.warning("after take: admin ask unread user=%s: %s", user_id, error)
        return False


def _no_phone(database: Any, user_id: str) -> bool:
    try:
        from services.whatsapp_notify import whatsapp_state
        return not whatsapp_state(database, str(user_id)).get("phone")
    except Exception as error:  # noqa: BLE001 -- unknown: do not ask
        logger.warning("after take: phone unread user=%s: %s", user_id, error)
        return False


def chain(database: Any, user_id: str, *, take_index: int, off: bool,
          can_install: bool = False, will: bool = False) -> list[str]:
    """The asks after this Take, in the order they come (see the module's
    table); [] when nothing waits. ``will``: Will has a question for this
    Take."""
    asks: list[str] = []
    if take_index >= 2 and _admin_ask(user_id):
        asks.append("admin")
    if _no_phone(database, user_id) and asked(database, user_id, "whatsapp") < _WHATSAPP_TIMES:
        asks.append("whatsapp")
    if take_index >= 2 and can_install and asked(database, user_id, "install") == 0:
        asks.append("install")
    if will:
        asks.append("will_question")
    if off:
        asks.append("feedback_check")
    return capped(asks)


def capped(asks: list[str]) -> list[str]:
    """The first ``_MOST`` of ``asks``, in their order; the others wait for
    a later Take (N189). Pure."""
    return list(asks[:_MOST])


def bridge_row(*, user_id: str, arc_id: str, take: str, take_index: Optional[int],
               at: str) -> dict:
    """The bridge line before Will's question, its own plain bubble (N94).
    Pure."""
    line = BRIDGE[max(0, (take_index or 1) - 1) % len(BRIDGE)]
    return {"client_id": str(uuid.uuid5(_NAMESPACE, f"{user_id}:{take}:bridge")),
            "role": "bot", "kind": "text", "body": line,
            "metadata": {"bridge": True, "arc_id": str(arc_id), "take_session_id": str(take)},
            "client_created_at": at}


def choose(database: Any, user_id: str, *, take_index: int, off: bool,
           can_install: bool = False, will: bool = False) -> Optional[str]:
    """The first ask of the chain, or None."""
    found = chain(database, user_id, take_index=take_index, off=off,
                  can_install=can_install, will=will)
    return found[0] if found else None


def signed_ask(ask: str) -> Optional[str]:
    """The signed words of an ask Will leads into; None for the others."""
    if ask in _OFFER_ASKS:
        from services.chat_app_context import OFFER_PROMPTS
        return OFFER_PROMPTS[ask]
    if ask == "feedback_check":
        from services.feedback_check import COPY
        return COPY["ask"]
    return None


def ask_rows(database: Any, ask: Optional[str], *, user_id: str, arc_id: str,
             take: str, at: str, will: Any = None,
             lead_in: Optional[str] = None, take_index: Optional[int] = None) -> list[dict]:
    """The ask's bubble, in the shape the Lounge draws as an offer, with
    Will's lead-in as its words when he has one. The CEO panel's ask is
    drawn by the Lounge itself (its price words live there), so it has no
    row here. ``will``: Will's plan (``will_question.Plan``) when his
    question is the ask; the bridge line comes before it."""
    if ask == "will_question":
        from services.will_question import ask_rows as will_rows
        wills = will_rows(will, user_id=user_id, at=_after(at, 1))
        if not wills:
            return []
        return [bridge_row(user_id=user_id, arc_id=arc_id, take=take,
                           take_index=take_index, at=at)] + wills
    if ask == "feedback_check":
        from services.feedback_check import ask_rows as question
        return question(database, user_id=user_id, arc_id=arc_id, take_session_id=take,
                        batch=[], at=at, text=lead_in)
    if ask not in _OFFER_ASKS:
        return []
    from services.chat_app_context import OFFER_PROMPTS
    return [{"client_id": str(uuid.uuid5(_NAMESPACE, f"{user_id}:{take}:{ask}")),
             "role": "bot", "kind": "text", "body": lead_in or OFFER_PROMPTS[ask],
             "metadata": {"offer": ask, "arc_id": arc_id, "take_session_id": take},
             "client_created_at": at}]


def start_lead_ins(database: Any, *, user_id: str, arc_id: str, take: str,
                   asks: list[str], facts: list[str]) -> Callable[[], dict]:
    """Will's lead-ins for the chain's asks that take one, started off the
    request beside the summary's own call; the call that collects them.
    Never raises: a lead-in not there in time means the ask as written."""
    wanted = {ask: signed_ask(ask) for ask in asks if ask in LEAD_IN_ASKS}
    signed = {ask: text for ask, text in wanted.items() if text}
    if not signed:
        return lambda: {}
    try:
        from services.will_question import start_lead_ins as start
        return start(database, user_id=user_id, arc_id=arc_id, take=take,
                     signed=signed, facts=facts)
    except Exception as error:  # noqa: BLE001 -- the asks as written
        logger.warning("after take: lead-ins not started take=%s: %s", take, error)
        return lambda: {}


def next_take_client_id(user_id: Any, arc_id: Any, take_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{user_id}:{arc_id}:take:{take_index}:next"))


def closing_row(*, user_id: str, arc_id: str, take_index: int, take: str, at: str,
                asks: list[str], lead_ins: Optional[dict] = None,
                queued: Optional[dict] = None) -> dict:
    """The closing message's row, held back behind the chain when there is
    one: ``held_for`` the ask in front of the speaker, ``chain`` the rest,
    ``lead_ins`` Will's words for the asks still to come, ``queued``
    rows already put together for them (Will's question) and ``plan_after``:
    the plan's lines after the Take wait for the chain too. Pure."""
    meta: dict[str, Any] = {"next_take": True, "arc_id": str(arc_id),
                            "take_index": take_index, "take_session_id": str(take)}
    if asks:
        meta.update({
            "held_for": asks[0], "chain": list(asks[1:]),
            "lead_ins": {k: v for k, v in (lead_ins or {}).items() if isinstance(v, str) and v},
            "queued": {k: v for k, v in (queued or {}).items() if v},
            "plan_after": True,
        })
    return {"client_id": next_take_client_id(user_id, arc_id, take_index), "role": "bot",
            "kind": "text", "body": NEXT_TAKE, "metadata": meta, "client_created_at": at}


def _after(at: str, ms: int) -> str:
    try:
        return (datetime.fromisoformat(at) + timedelta(milliseconds=ms)).isoformat()
    except ValueError:
        return at


def rows_for(database: Any, user_id: str, meta: dict, ask: str, at: str) -> list[dict]:
    """The rows of one ask of the chain, as written when its turn comes:
    Will's question as put together with the summary (``queued``), the
    others with his lead-in. [] for the CEO panel's ask (the Lounge draws
    it) and for an ask that cannot be written."""
    if ask == "admin":
        return []
    if ask == "will_question":
        rows = [dict(r) for r in (meta.get("queued") or {}).get("will_question") or []
                if isinstance(r, dict)]
        for i, row in enumerate(rows):
            row["client_created_at"] = _after(at, i)
        return rows
    lead = (meta.get("lead_ins") or {}).get(ask)
    return ask_rows(database, ask, user_id=user_id, arc_id=str(meta.get("arc_id") or ""),
                    take=str(meta.get("take_session_id") or ""), at=at,
                    lead_in=lead if isinstance(lead, str) and lead else None)


def _is_held(row: dict, take: Optional[str] = None) -> bool:
    meta = row.get("metadata") or {}
    # The summary itself was the held message in the chain's first form
    # (the morning of 2026-10-20); a row of that form still waiting is read.
    return ((meta.get("next_take") is True or meta.get("summary") is True)
            and bool(meta.get("held_for"))
            and (take is None or meta.get("take_session_id") == take))


def held(database: Any, user_id: str, take: Optional[str] = None) -> Optional[dict]:
    """The newest message still held back (for this Take, when given)."""
    return next((r for r in _rows(database, user_id, _LOOK) if _is_held(r, take)), None)


def glad_body(text: str) -> str:
    """``text`` with ``GLAD`` before its last line (the first form's held
    summary, where the next step stayed the last thing said). Pure."""
    if not text or GLAD in text:
        return text
    head, sep, last = text.rpartition("\n\n")
    if sep:
        return f"{head}\n\n{GLAD} {last}"
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    return " ".join(sentences[:-1] + [GLAD, sentences[-1]]) if sentences else text


_CHAIN_KEYS = ("held_for", "chain", "lead_ins", "queued", "plan_after")


def _let_go(database: Any, user_id: str, row: dict, *, glad: bool, at: Optional[str]) -> Optional[dict]:
    meta = {k: v for k, v in (row.get("metadata") or {}).items() if k not in _CHAIN_KEYS}
    body = row.get("body") or ""
    if glad and meta.get("summary") is True:
        body, meta["glad"] = glad_body(body), True
    return database.rewrite_lounge_message(str(user_id), row["client_id"], body, meta, at=at)


def _applies(database: Any, user_id: str, ask: str) -> bool:
    """Whether an ask still applies when its turn comes."""
    if ask == "whatsapp":
        return _no_phone(database, user_id)
    if ask == "admin":
        return _admin_ask(user_id)
    return True


def release(database: Any, user_id: str, *, take: Optional[str] = None,
            glad: bool = False) -> list[dict]:
    """Advance the chain under the newest row of the thread: the next ask's
    rows, written now (the closing message stays held, in front of it); or,
    with nothing left, the closing message let go. The rows written, or []
    when nothing was held. Best-effort: never raises."""
    try:
        row = held(database, user_id, take)
        if not row:
            return []
        from services.lounge_messages import thread_stamp
        at = thread_stamp(database, user_id)
        meta = dict(row.get("metadata") or {})
        left = [a for a in (meta.get("chain") or []) if isinstance(a, str)]
        while left:
            ask = left.pop(0)
            if not _applies(database, user_id, ask):
                continue
            rows = rows_for(database, str(user_id), meta, ask, at)
            if ask != "admin" and not rows:
                continue
            meta.update({"held_for": ask, "chain": left})
            kept = database.rewrite_lounge_message(str(user_id), row["client_id"],
                                                   row.get("body") or "", meta, at=None)
            if rows:
                return database.insert_lounge_messages(str(user_id), rows) or []
            return [kept] if kept else []
        # The plan's lines after the Take ("That's your 15 minutes for
        # today.") come once the asks are answered, never over one: written
        # over Will's question they hid its answers and let this go early.
        plan_rows: list[dict] = []
        if meta.get("plan_after"):
            from services.plan_flow import after_take as plan_after_take
            plan_rows = plan_after_take(database, user_id)
            at = thread_stamp(database, user_id) if plan_rows else at
        gone = _let_go(database, user_id, row, glad=glad, at=at)
        return plan_rows + ([gone] if gone else [])
    except Exception as error:  # noqa: BLE001 -- the Lounge advances it on its next close
        logger.warning("after take: not advanced user=%s: %s", user_id, error, exc_info=True)
        return []


def release_older(database: Any, user_id: str) -> None:
    """Before a newer Take's batch: a message still held from an older Take
    is let go where it stands. Best-effort."""
    try:
        row = held(database, user_id)
        if row:
            _let_go(database, user_id, row, glad=False, at=None)
    except Exception as error:  # noqa: BLE001 -- the new Take is written either way
        logger.warning("after take: older not let go user=%s: %s", user_id, error, exc_info=True)


def passes(resp: dict) -> bool:
    """Does this chat reply pass the open ask? Not when it keeps an ask
    open: "What would help?" and Will's follow-up wait for their answer, and
    a reply that opens a form (a number without its country code) waits for
    the form. Pure."""
    meta = resp.get("row_metadata") or {}
    return (not resp.get("offer") and meta.get("feedback_check") != "missing"
            and meta.get("will_question_step") != "follow")
