"""Did this feedback help? (WIL-74 phase 1, founder 2026-10-19, words signed
the same day). Table: take_feedback_checks, one row per Take.

The chat's own module for one question after the Feedback walk:

  1. ``ask_rows``: the closing summary (``take_summary``) is written; the
     question follows it in the Lounge, in the shape the Lounge already draws
     as an offer (kind text + metadata.offer), so the footer shows
     Not really | Yes in place of the record button. Never in the way of the
     next Take: the record button is back the moment they answer, and an
     ignored question stays a bubble in the thread.
  2. ``answer``: Yes → "Noted. Thank you."; Not really → "What was
     missing?" with a Skip button; Skip → "Noted. Thank you.".
  3. ``chat_turn``: the chat's intercept. What the speaker types under
     "What was missing?" is their answer: it is saved and answered with the
     signed words, before any other voice can claim it. Typing "Yes" or
     "Not really" under the question counts as tapping it.

Checked against the fixed messages after a Take (``check_against_after_take``):
the question is the last row of the summary's batch, and it is NOT asked when
another offer rides in that batch (today: the WhatsApp offer). One ask at a
time; it is asked after a later Take instead. A coach update that rewrites the
summary does not ask again (the summary's batch is written once per Take).

No number, score or verdict reaches the speaker (CLAUDE.md, Never 1): the
answer is stored for the founder, and the speaker only ever reads the signed
words below. Fixed English words, like the Lounge's other offers.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("6b0d3f52-74a1-4c5e-9d2b-7e1c0a9f4b11")

#: The signed words (founder 2026-10-19). No new words without the founder's OK.
COPY = {
    "ask": "Did this feedback help you?",
    "yes": "Yes",
    "not_really": "Not really",
    "missing": "What was missing?",
    "skip": "Skip",
    "thanks": "Noted. Thank you.",
}
OFFER = "feedback_check"
#: The Skip button under "What was missing?" (the Lounge's chip vocabulary).
SKIP_ACTION = "feedback_skip"
CHOICES = ("yes", "not_really", "skip")
_MAX_MISSING = 2000
#: How far back the chat looks for the question it may be answering.
_LOOKBACK = 6


class CheckError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _after(at: str, ms: int) -> str:
    """``at`` moved ``ms`` milliseconds on: the thread is ordered by time, and
    the rows of one write must keep their order (the question after the
    summary, the reply after the tap)."""
    try:
        return (datetime.fromisoformat(at) + timedelta(milliseconds=ms)).isoformat()
    except ValueError:
        return at


def _cid(user_id: str, take: str, part: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{user_id}:{take}:{part}"))


def _row(client_id: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": client_id, "role": role, "kind": "text", "body": body,
            "metadata": meta, "client_created_at": at}


def check_against_after_take(batch: list[dict]) -> bool:
    """May the question follow this batch of fixed after-Take rows? Not when
    another offer already rides in it: one ask at a time. Pure."""
    return not any((r.get("metadata") or {}).get("offer") for r in batch)


def ask_rows(database: Any, *, user_id: str, arc_id: str, take_session_id: str,
             batch: list[dict], at: str) -> list[dict]:
    """The question, to append after the summary's ``batch``; [] when it
    must wait for a later Take. Best-effort: never raises."""
    try:
        if not check_against_after_take(batch):
            return []
        database.save_take_feedback_check({
            "user_id": user_id, "arc_id": arc_id,
            "take_session_id": take_session_id, "asked_at": at})
        return [_row(_cid(user_id, take_session_id, "ask"), "bot", COPY["ask"],
                     {"offer": OFFER, "arc_id": arc_id,
                      "take_session_id": take_session_id}, _after(at, 5))]
    except Exception as error:  # noqa: BLE001 -- the summary is written either way
        logger.warning("feedback check: not asked take=%s: %s", take_session_id, error, exc_info=True)
        return []


def _save(database: Any, user_id: str, arc_id: Optional[str], take: str, **fields) -> None:
    if not database.save_take_feedback_check({
            "user_id": user_id, "arc_id": arc_id, "take_session_id": take,
            "answered_at": _now(), **fields}):
        raise CheckError("V2_ERROR", "Failed to save the answer", 500)


def answer(database: Any, *, user_id: str, arc_id: str, take_session_id: str,
           choice: str) -> list[dict]:
    """A tap on Yes, Not really or Skip: stores it and writes the thread's
    rows (their tap and the signed reply). A repeat tap writes nothing and
    returns []. Raises ``CheckError``."""
    if choice not in CHOICES:
        raise CheckError("INVALID_CHOICE", "Unknown answer.")
    take = str(take_session_id)
    held = database.get_take_feedback_check(user_id, take) or {}
    # Under the question it answers, whatever the browser's clock said.
    from services.lounge_messages import thread_stamp
    at = thread_stamp(database, user_id)
    meta = {"feedback_check": choice, "arc_id": arc_id, "take_session_id": take}
    if choice == "skip":
        if held.get("helped") is not False or held.get("missing") or held.get("skipped"):
            return []
        _save(database, user_id, arc_id, take, skipped=True)
        reply = _row(_cid(user_id, take, "thanks"), "bot", COPY["thanks"], meta,
                     _after(at, 1))
    else:
        if held.get("answered_at"):
            return []
        _save(database, user_id, arc_id, take, helped=choice == "yes")
        if choice == "yes":
            reply = _row(_cid(user_id, take, "thanks"), "bot", COPY["thanks"], meta,
                         _after(at, 1))
        else:
            reply = _row(_cid(user_id, take, "missing"), "bot", COPY["missing"],
                         {**meta, "feedback_check": "missing",
                          "suggested_action": SKIP_ACTION}, _after(at, 1))
    mine = _row(_cid(user_id, take, choice), "user", COPY[choice], meta, at)
    return database.insert_lounge_messages(user_id, [mine, reply]) or []


def _review_card(row: dict) -> bool:
    return row.get("kind") == "walk_step" and (row.get("metadata") or {}).get("step") == "end"


def _open_question(database: Any, user_id: str) -> Optional[dict]:
    """The newest bot row in the thread when it is this module's question
    ("ask" or "missing") and is still open; None otherwise. The speaker's
    own rows are skipped (the client stores the turn before asking), and so
    is the review's Ideal Text card: it is stored when the speaker leaves
    the summary, after the question, but the chat draws it above the
    summary (founder 2026-10-20: the chat reads what it shows, in order)."""
    rows = database.get_lounge_messages_page(str(user_id), limit=_LOOKBACK) or []
    bot = next((r for r in rows if r.get("role") == "bot" and not _review_card(r)), None)
    meta = (bot or {}).get("metadata") or {}
    step = "ask" if meta.get("offer") == OFFER else meta.get("feedback_check")
    take = meta.get("take_session_id")
    if step not in ("ask", "missing") or not take:
        return None
    held = database.get_take_feedback_check(str(user_id), str(take)) or {}
    if step == "ask" and held.get("answered_at"):
        return None
    if step == "missing" and (held.get("missing") or held.get("skipped")
                              or held.get("helped") is not False):
        return None
    return {"step": step, "arc_id": meta.get("arc_id"), "take_session_id": str(take)}


def _said(question: str) -> Optional[str]:
    """The typed words when they are one of the buttons, else None."""
    said = question.strip().rstrip(".!").lower()
    return next((c for c in ("yes", "not_really")
                 if said == COPY[c].lower()), None)


def chat_turn(database: Any, user_id: str, question: str) -> Optional[dict]:
    """The chat's intercept: ``{"answer", "row_metadata"}`` when this turn
    answers the open question, else None (the turn goes on to the next
    voice). The metadata rides on the stored reply, so "What was missing?"
    asked from the chat is the same question as the one a tap writes."""
    if not user_id or not question.strip():
        return None
    open_q = _open_question(database, user_id)
    if not open_q:
        return None
    take, arc_id = open_q["take_session_id"], open_q["arc_id"]
    meta = {"arc_id": arc_id, "take_session_id": take}
    if open_q["step"] == "missing":
        _save(database, str(user_id), arc_id, take,
              missing=question.strip()[:_MAX_MISSING])
        return {"answer": COPY["thanks"],
                "row_metadata": {**meta, "feedback_check": "missing_answered"}}
    choice = _said(question)
    if not choice:
        return None  # an ordinary turn; Will sees the question in the thread
    _save(database, str(user_id), arc_id, take, helped=choice == "yes")
    if choice == "yes":
        return {"answer": COPY["thanks"],
                "row_metadata": {**meta, "feedback_check": "yes"}}
    return {"answer": COPY["missing"],
            "row_metadata": {**meta, "feedback_check": "missing",
                             "suggested_action": SKIP_ACTION}}
