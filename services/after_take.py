"""One action at a time after a Take (founder 2026-10-20: "You cannot have
two actions at a time, like feedback and record"; the details chosen on the
decisions page the same day).

After the Feedback walk the Lounge shows the Take's card, then at most ONE
ask, then the message after the Take with "Record Take N". The message is
written with the summary's batch (``take_summary``) but held back
(``metadata.held_for`` names the ask) and let go under whatever closed the
ask. Which ask (``choose``):

  Take 1      "Did this help?", only when the Take looks off
              (``feedback_check.looks_off``). Never WhatsApp, never an ask
              from the CEO panel.
  Take 2 on   the founder's ask from the CEO panel when one is open
              ("admin"; the Lounge shows it, and "Not now" leaves it open,
              so it comes back at the end of the next Take); else WhatsApp,
              while there is no number and it was asked fewer than twice;
              else the home screen, once, where the phone can add it; else
              "Did this help?" when the Take looks off.

Let go (``release``), always under the rows that closed the ask:
  - "Yes": with ``GLAD`` before its last line; "Skip", or the answer to
    "What would help?": as written (``feedback_check``);
  - a typed turn that passes the ask, under Will's reply
    (``chat_query.finish_chat_turn``);
  - the ask's form closing in the Lounge, whatever the choice (Save, Not
    now, See prices): POST /v2/user/lounge/after-take;
  - a newer Take's summary: an older held message is let go where it stands.

Nothing here blocks the next Take: one tap on the ask (Not now, Skip, No)
brings the message and its record button. No number, score or verdict, and
no new words but ``GLAD`` (the founder's own, chosen 2026-10-20).
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("9a3e6c1d-52b7-4f08-8d41-c7e2b05f9a63")

#: The founder's sentence after "Yes" (decisions page, 2026-10-20).
GLAD = "We're glad it helped you."
#: Asks the Lounge draws from the summary's batch as offer bubbles.
_OFFER_ASKS = ("whatsapp", "install")
#: WhatsApp is asked at most this many times (founder 2026-10-20).
_WHATSAPP_TIMES = 2
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


def choose(database: Any, user_id: str, *, take_index: int, off: bool,
           can_install: bool = False) -> Optional[str]:
    """The one ask after this Take, or None (see the module's table)."""
    if take_index >= 2:
        if _admin_ask(user_id):
            return "admin"
        if _no_phone(database, user_id) and asked(database, user_id, "whatsapp") < _WHATSAPP_TIMES:
            return "whatsapp"
        if can_install and asked(database, user_id, "install") == 0:
            return "install"
    return "feedback_check" if off else None


def ask_rows(database: Any, ask: Optional[str], *, user_id: str, arc_id: str,
             take: str, at: str) -> list[dict]:
    """The ask's bubble after the held message, in the shape the Lounge
    draws as an offer. The CEO panel's ask is drawn by the Lounge itself
    (its price words live there), so it has no row here."""
    if ask == "feedback_check":
        from services.feedback_check import ask_rows as question
        return question(database, user_id=user_id, arc_id=arc_id, take_session_id=take,
                        batch=[], at=at)
    if ask not in _OFFER_ASKS:
        return []
    from services.chat_app_context import OFFER_PROMPTS
    return [{"client_id": str(uuid.uuid5(_NAMESPACE, f"{user_id}:{take}:{ask}")),
             "role": "bot", "kind": "text", "body": OFFER_PROMPTS[ask],
             "metadata": {"offer": ask, "arc_id": arc_id, "take_session_id": take},
             "client_created_at": at}]


def _is_held(row: dict, take: Optional[str] = None) -> bool:
    meta = row.get("metadata") or {}
    return (meta.get("summary") is True and bool(meta.get("held_for"))
            and (take is None or meta.get("take_session_id") == take))


def held(database: Any, user_id: str, take: Optional[str] = None) -> Optional[dict]:
    """The newest message still held back (for this Take, when given)."""
    return next((r for r in _rows(database, user_id, _LOOK) if _is_held(r, take)), None)


def glad_body(text: str) -> str:
    """``text`` with ``GLAD`` before its last line: the next step stays the
    last thing said. Pure."""
    if not text or GLAD in text:
        return text
    head, sep, last = text.rpartition("\n\n")
    if sep:
        return f"{head}\n\n{GLAD} {last}"
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    return " ".join(sentences[:-1] + [GLAD, sentences[-1]]) if sentences else text


def _let_go(database: Any, user_id: str, row: dict, *, glad: bool, at: Optional[str]) -> Optional[dict]:
    meta = {k: v for k, v in (row.get("metadata") or {}).items() if k != "held_for"}
    body = row.get("body") or ""
    if glad:
        body, meta["glad"] = glad_body(body), True
    return database.rewrite_lounge_message(str(user_id), row["client_id"], body, meta, at=at)


def release(database: Any, user_id: str, *, take: Optional[str] = None,
            glad: bool = False) -> Optional[dict]:
    """Let the held message go, under the newest row of the thread. The row
    as stored, or None when nothing was held. Best-effort: never raises."""
    try:
        row = held(database, user_id, take)
        if not row:
            return None
        from services.lounge_messages import thread_stamp
        return _let_go(database, user_id, row, glad=glad, at=thread_stamp(database, user_id))
    except Exception as error:  # noqa: BLE001 -- the Lounge lets it go on its next close
        logger.warning("after take: not let go user=%s: %s", user_id, error, exc_info=True)
        return None


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
    open: "What would help?" waits for its answer, and a reply that opens a
    form (a number without its country code) waits for the form. Pure."""
    meta = resp.get("row_metadata") or {}
    return not resp.get("offer") and meta.get("feedback_check") != "missing"
