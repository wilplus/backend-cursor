"""One action at a time after a Take, in a chain (founder 2026-10-20, N89,
after checking the app; the first form, one ask per Take, the same
morning), ending without a push to the next Take (founder 2026-10-31,
N294; N319 item 7).

After the Feedback walk the Lounge shows the Take's card and the summary
(``take_summary``): what the Take showed, with no next step and no record
button. Then, one at a time, each after the one before is answered: every
ask that waits; and only then the closing message ("Good job. See you next
time.", ``SEE_YOU``). The closing message is written with the summary's
batch but held back (``metadata.held_for`` names the ask in front of the
speaker, ``metadata.chain`` the asks still to come) and advances under
whatever closed the ask (``release``). The asks (``chain``), in order:

  Take 1      Will's question when he has one (``will_question``); "Did this
              help?" when the Take looks off (``feedback_check.looks_off``).
              Never an ask from the CEO panel.
  Take 2 on   the founder's ask from the CEO panel when one is open
              ("admin"; the Lounge draws it, and "Not now" leaves it open,
              so it comes back at the end of the next Take); then Will's
              question when he has one; then "Did this help?" when the Take
              looks off.

One ask a Take (founder 2026-10-26, N189): the first that waits, in the
order above; the others wait for a later Take. Will's question may be
followed by his next one (N294 item 4, "will_next": what they should do,
after who the talk is for, when both are missing), only once the first is
answered; a Skip ends them.

The settings asks wait for the next visit (founder 2026-10-31, N294 item 8,
N295; ``visit``): WhatsApp and the home screen are never asked after a
Take. They come the next time the speaker opens the app, one at a time and
one per Take, never before their second Take is done, WhatsApp first ("It
seems you enjoy using WillpowerLab." and its signed ask, at most twice in
all), the home screen last ("Well, I can see you're doing pretty good." and
its signed ask, once, where the phone can add it). Was: the Take's one ask,
WhatsApp from Take 1 (N171), the home screen from Take 2.

Will's question opens with a bridge line in the chat (``BRIDGE``, founder
2026-10-21, N94), between the summary and the question: two signed lines,
one a Take in turn. Only the chat has it, never the walk.

Will's lead-in (``will_question.lead_in``, started beside the summary's
own call and under the Take's authority): one or two sentences tied to
this Take before the ask's signed words said with a light touch, for "Did
this help?" (``LEAD_IN_ASKS``). Will's own question needs none, and the CEO
panel's asks are drawn as written (their prices carry numbers; the data
question's words belong to the consent screen). A lead-in that fails its
checks, or came too late, means the ask as written.

Advancing (``release``), always under the rows that closed the ask:
  - "Yes" to "Did this help?": ``GLAD`` as the reply, then the next ask;
    "Skip", or the answer to "What would help?": under "Thanks!"
    (``feedback_check``);
  - Will's question answered (a tap with no follow-up, Skip, or typed
    words), under his reply (``will_question``);
  - a typed turn that passes the ask, under Will's reply
    (``chat_query.finish_chat_turn``); never under the chat's safety reply:
    after a distressed message the asks wait until the speaker writes
    again (founder 2026-10-21, N94);
  - the ask's form closing in the Lounge, whatever the choice (Save, Not
    now, See prices): POST /v2/user/lounge/after-take;
  - a newer Take's summary: an older held message is let go where it stands.
An ask that no longer applies when its turn comes is skipped. When the
chain is empty the end comes (``end_rows``): the plan's lines after the
Take (``plan_flow.after_take``, "That's your 15 minutes for today."), the
closing message ("Good job. See you next {day}." on a plan, with its next
practice day), then on a plan its progress, the plan's bar and "{n} of
{total} practices done." (``plan_flow.progress``, N319 item 7). The Lounge
puts the tap "I want to continue my practice" under the last of them;
tapping it, or typing that they want to practise, brings "Record Take N"
under the chat (frontend ``afterTake.ts``). The plan's lines wait for the
chain: written over an ask, they hid its answers and let the closing
message go.

Nothing here blocks the next Take: one tap on each ask (Not now, Skip, No)
brings the next, and the closing message after the last; not answering is
allowed, the "+" still opens the projects, and the Ideal Text page's own
"Record Take N" is never held. No number, score or verdict (the plan's
count of practices aside, Never 1), and the only words are the founder's
(``GLAD``, 2026-10-20; ``SEE_YOU``, ``SEE_YOU_ON`` and the visit's openers,
2026-10-31 and 2026-11-01).
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
#: The closing message, once every ask is answered: no push to the next
#: Take (founder 2026-10-31, N294 item 6; was "Look, practice makes
#: perfect…" with "Record Take N", N89). The Lounge puts "I want to continue
#: my practice" under it.
SEE_YOU = "Good job. See you next time."
#: On a plan, its next practice day (N319 item 7).
SEE_YOU_ON = "Good job. See you next {day}."
#: The settings asks of the next visit, in their order, each with its opener
#: (founder 2026-10-31, N294 item 8, N295).
VISIT_ASKS = ("whatsapp", "install")
VISIT_OPENERS = {
    "whatsapp": "It seems you enjoy using WillpowerLab.",
    "install": "Well, I can see you're doing pretty good.",
}
#: The asks Will opens with a lead-in line (``will_question.lead_in``).
LEAD_IN_ASKS = ("feedback_check",)
#: The asks a held message from before N294 may still name: never written
#: after a Take now, they wait for the next visit.
_SETTINGS_ASKS = ("whatsapp", "install")
#: WhatsApp is asked at most this many times (founder 2026-10-20).
_WHATSAPP_TIMES = 2
#: A visit's settings ask comes once the speaker has done this many Takes
#: (N294 item 8: never before their second).
_VISIT_FROM = 2
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
          will: bool = False, will_next: bool = False) -> list[str]:
    """The asks after this Take, in the order they come (see the module's
    table); [] when nothing waits. ``will``: Will has a question for this
    Take; ``will_next``: and a second one may follow it once answered
    (N294 item 4)."""
    asks: list[str] = []
    if take_index >= 2 and _admin_ask(user_id):
        asks.append("admin")
    if will:
        asks.append("will_question")
    if off:
        asks.append("feedback_check")
    first = capped(asks)
    return first + (["will_next"] if will_next and first == ["will_question"] else [])


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
           will: bool = False) -> Optional[str]:
    """The first ask of the chain, or None."""
    found = chain(database, user_id, take_index=take_index, off=off, will=will)
    return found[0] if found else None


def signed_ask(ask: str) -> Optional[str]:
    """The signed words of an ask Will leads into; None for the others."""
    if ask == "feedback_check":
        from services.feedback_check import COPY
        return COPY["ask"]
    return None


def ask_rows(database: Any, ask: Optional[str], *, user_id: str, arc_id: str,
             take: str, at: str, will: Any = None,
             lead_in: Optional[str] = None, take_index: Optional[int] = None) -> list[dict]:
    """The ask's bubble, with Will's lead-in as its words when he has one.
    The CEO panel's ask is drawn by the Lounge itself (its price words live
    there), so it has no row here. ``will``: Will's plan
    (``will_question.Plan``) when his question is the ask; the bridge line
    comes before it, and before his next question nothing."""
    if ask == "will_question":
        from services.will_question import ask_rows as will_rows
        wills = will_rows(will, user_id=user_id, at=_after(at, 1))
        if not wills:
            return []
        return [bridge_row(user_id=user_id, arc_id=arc_id, take=take,
                           take_index=take_index, at=at)] + wills
    if ask == "will_next":
        from services.will_question import next_rows
        return next_rows(will, user_id=user_id, at=at)
    if ask == "feedback_check":
        from services.feedback_check import ask_rows as question
        return question(database, user_id=user_id, arc_id=arc_id, take_session_id=take,
                        batch=[], at=at, text=lead_in)
    return []


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


def closing_line(day: Optional[str] = None) -> str:
    """The closing message: "Good job. See you next {day}." with the plan's
    next practice day, else "Good job. See you next time." Pure."""
    return SEE_YOU_ON.format(day=day) if day else SEE_YOU


def closing_row(*, user_id: str, arc_id: str, take_index: int, take: str, at: str,
                asks: list[str], lead_ins: Optional[dict] = None,
                queued: Optional[dict] = None) -> dict:
    """The closing message's row, held back behind the chain when there is
    one: ``held_for`` the ask in front of the speaker, ``chain`` the rest,
    ``lead_ins`` Will's words for the asks still to come, ``queued``
    rows already put together for them (Will's questions), and
    ``plan_after`` (the plan's lines come when the chain is done). Its
    words are set when it is let go (``end_rows``). Pure."""
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
            "kind": "text", "body": SEE_YOU, "metadata": meta, "client_created_at": at}


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
    if ask in ("will_question", "will_next"):
        rows = [dict(r) for r in (meta.get("queued") or {}).get(ask) or []
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


def _let_go(database: Any, user_id: str, row: dict, *, glad: bool, at: Optional[str],
            body: Optional[str] = None) -> Optional[dict]:
    meta = {k: v for k, v in (row.get("metadata") or {}).items() if k not in _CHAIN_KEYS}
    text = body if body and meta.get("next_take") is True else (row.get("body") or "")
    if glad and meta.get("summary") is True:
        text, meta["glad"] = glad_body(text), True
    return database.rewrite_lounge_message(str(user_id), row["client_id"], text, meta, at=at)


def _applies(database: Any, user_id: str, ask: str, take: str) -> bool:
    """Whether an ask still applies when its turn comes. A settings ask a
    held message from before N294 still names waits for the next visit;
    Will's next question only follows an answered first one."""
    if ask in _SETTINGS_ASKS:
        return False
    if ask == "admin":
        return _admin_ask(user_id)
    if ask == "will_next":
        from services.will_question import skipped
        return not skipped(database, user_id, take)
    return True


def _plan_day(database: Any, user_id: str) -> Optional[str]:
    try:
        from services.plan_flow import next_day_name
        return next_day_name(database, user_id)
    except Exception as error:  # noqa: BLE001 -- "See you next time."
        logger.warning("after take: plan day unread user=%s: %s", user_id, error)
        return None


def _plan_progress(database: Any, user_id: str) -> list[dict]:
    try:
        from services.plan_flow import progress
        return progress(database, user_id)
    except Exception as error:  # noqa: BLE001 -- the closing message stands alone
        logger.warning("after take: plan progress not written user=%s: %s", user_id, error)
        return []


def end_rows(database: Any, user_id: str, row: dict, *, glad: bool = False,
             plan_after: bool = True, written: bool = True) -> list[dict]:
    """The end of the chat after a Take, once nothing is asked (N294 item 6,
    N319 item 7): the plan's lines after the Take, then the closing message
    under them ("Good job. See you next {day}." on a plan), then the plan's
    progress under it. ``row``: the closing message, let go where it was
    held (``written``) or written now. The rows written."""
    from services.lounge_messages import thread_stamp
    from services.plan_flow import after_take as plan_after_take
    plan_rows = plan_after_take(database, user_id) if plan_after else []
    body = closing_line(_plan_day(database, user_id))
    at = thread_stamp(database, user_id)
    if written:
        gone = _let_go(database, user_id, row, glad=glad, at=at, body=body)
        closing = [gone] if gone else []
    else:
        closing = database.insert_lounge_messages(str(user_id), [{
            **row, "body": body, "client_created_at": at}]) or []
    return plan_rows + closing + (_plan_progress(database, user_id) if closing else [])


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
            if not _applies(database, user_id, ask, str(meta.get("take_session_id") or "")):
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
        if meta.get("next_take") is not True:
            # The chain's first form held the summary itself: let go as it was.
            gone = _let_go(database, user_id, row, glad=glad, at=at)
            return [gone] if gone else []
        return end_rows(database, user_id, row, glad=glad, plan_after=bool(meta.get("plan_after")))
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


def _takes_done(rows: list[dict]) -> list[str]:
    """The Takes whose walk reached its summary, newest first (``rows``:
    the thread, newest first). Pure."""
    seen: list[str] = []
    for r in rows:
        meta = r.get("metadata") or {}
        take = meta.get("take_session_id")
        if (meta.get("next_take") is True or meta.get("summary") is True) and isinstance(take, str) \
                and take and take not in seen:
            seen.append(take)
    return seen


def _visit_ask(database: Any, user_id: str, rows: list[dict], can_install: bool) -> Optional[str]:
    """The settings ask the next visit brings, WhatsApp first, the home
    screen last; None when neither applies."""
    if (_no_phone(database, user_id)
            and sum(1 for r in rows if (r.get("metadata") or {}).get("offer") == "whatsapp") < _WHATSAPP_TIMES):
        return "whatsapp"
    if can_install and not any((r.get("metadata") or {}).get("offer") == "install" for r in rows):
        return "install"
    return None


def visit(database: Any, user_id: str, *, can_install: bool = False) -> list[dict]:
    """The speaker opened the app (the Lounge loading, once a visit): one
    settings ask, when one waits (founder 2026-10-31, N294 item 8, N295).
    Never before their second Take is done, never while an ask after a Take
    is in front of them, and at most one per Take: the next waits for the
    next visit after the next Take. Its opener, then its signed words; the
    Lounge opens its form. The rows written, [] when nothing is asked.
    Best-effort: never raises."""
    try:
        rows = _rows(database, user_id, _SCAN)
        takes = _takes_done(rows)
        if len(takes) < _VISIT_FROM or any(_is_held(r) for r in rows[:_LOOK]):
            return []
        newest = takes[0]
        if any((r.get("metadata") or {}).get("visit_after") == newest for r in rows):
            return []  # this Take's visit already asked
        from services.will_question import open_question
        if open_question(database, str(user_id)):
            return []
        ask = _visit_ask(database, user_id, rows, can_install)
        if not ask:
            return []
        from services.chat_app_context import OFFER_PROMPTS
        from services.lounge_messages import thread_stamp
        return database.insert_lounge_messages(str(user_id), [{
            "client_id": str(uuid.uuid5(_NAMESPACE, f"{user_id}:{newest}:visit:{ask}")),
            "role": "bot", "kind": "text",
            "body": f"{VISIT_OPENERS[ask]} {OFFER_PROMPTS[ask]}",
            "metadata": {"offer": ask, "visit_after": newest, "take_session_id": newest},
            "client_created_at": thread_stamp(database, user_id)}]) or []
    except Exception as error:  # noqa: BLE001 -- the Lounge opens either way
        logger.warning("after take: visit ask not written user=%s: %s", user_id, error, exc_info=True)
        return []


def passes(resp: dict) -> bool:
    """Does this chat reply pass the open ask? Not when it keeps an ask
    open: "What would help?" and Will's follow-up wait for their answer, and
    a reply that opens a form (a number without its country code) waits for
    the form. Pure."""
    meta = resp.get("row_metadata") or {}
    return (not resp.get("offer") and meta.get("feedback_check") != "missing"
            and meta.get("will_question_step") != "follow")
