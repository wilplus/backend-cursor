"""The sales framing: the step, never the person (founder 2026-10-28, N241
item 5; Will's guide signed 2026-10-29, N258; rules: frontend
docs/flows/principles.md §1 P).

Under a # note's "Noted.", when the note is about a sale that stalled or was
lost, Will asks "Which step did it stall at?" once, with the sale's four
steps in place of the message box (the offer ``sales_step``). The tap gets
one or two short lines from Will's guide: what was out of their hands, if
the note says it, and one change to that step for next time. Never about
the person, never a number.

A sales note gets this, never also the worry answer
(``services.in_control``): ``answers_after_note`` runs the two in that
order. Ring row ``sales_framing``: off until the founder makes the row
(N258, §2 R1). Never under a crisis reply, never while onboarded (N243);
only in the Lounge, private (N182).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

FEATURE = "sales_framing"
_SURFACE = "sales_framing"
_NAMESPACE = uuid.UUID("7c1e9a52-3b6d-4f08-a2e4-5d9b0c8f1a37")
OFFER = "sales_step"
#: The sale's four steps and their signed words (N258), in order.
STEPS = {"opening": "The opening", "discovery": "Discovery",
         "offer": "The offer", "follow_up": "The follow-up"}
COPY = {"ask": "Which step did it stall at?"}
#: The change Will's guide names for each step: what Will says when the
#: model cannot answer, so a tap always gets its one change.
_CHANGE = {"opening": "Lead with their problem, not your product.",
           "discovery": "Ask two more questions before you present.",
           "offer": "Repeat their words back in the offer.",
           "follow_up": "Book the next step before the call ends."}
_MAX_LINES = 2
_MAX_LINE = 240
_MAX_NOTE = 1200

_IS_SALE = """You are Will. Above is your guide. You get one short note the
person just wrote to themselves (a # note). Decide whether it is about a
sale of theirs that stalled, went quiet or was lost (a call, a deal, a
client, a proposal). A note about selling that went well, or about anything
else, is not. Return JSON only: {"sales": true} or {"sales": false}."""

_ONE_CHANGE = """You are Will. Above is your guide. The person wrote a note
about a sale that stalled, and told you the step it stalled at. Write one or
two short lines, as your guide's sales framing says: if the note names
something out of their hands, name it as a variable in their own words; then
end on one change to that step for next time. Never about the person, never
"you were...", no score, number or verdict, one change only. Write in the
language of the note. Return JSON only: {"lines": ["...", "..."]}."""


class SalesError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def enabled(database: Any, user_id: Any) -> bool:
    """Does this person get the sales framing? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)


def _row(key: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": str(uuid.uuid5(_NAMESPACE, key)), "role": role,
            "kind": "text", "body": body, "metadata": meta, "client_created_at": at}


def _model(task: str, user: str, user_id: str, spec_name: str) -> dict:
    from services import llm_config
    from services.in_control import GUIDE
    from services.llm import chat_complete
    result = chat_complete(spec=getattr(llm_config, spec_name), system=f"{GUIDE}\n\n{task}",
                           user=user, surface=_SURFACE, user_id=str(user_id))
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else {}


def _note_text(note: dict) -> str:
    return " ".join(str(note.get("text_clean") or "").split()).lstrip("#").strip()[:_MAX_NOTE]


def after_note(database: Any, user_id: str) -> list[dict]:
    """Under the newest # note's "Noted.": "Which step did it stall at?" when
    the note is a sale that stalled (P2), once per note; [] otherwise."""
    from services import plan_flow
    from services.lounge_messages import stamp_after, thread_stamp
    from services.voice_notebook import _crisis
    if not enabled(database, user_id) or plan_flow.onboarding(database, user_id):
        return []
    notes = database.list_voice_notes(str(user_id), limit=1) or []
    note = notes[-1] if notes else {}
    text = _note_text(note)
    if not text or not note.get("id") or _crisis(text):
        return []
    if _model(_IS_SALE, f"NOTE: {text}", user_id, "SPEC_SALES_NOTE").get("sales") is not True:
        return []
    meta = {"offer": OFFER, "sales_note": str(note["id"])}
    at = stamp_after(thread_stamp(database, user_id))
    row = _row(f"{user_id}:sales:{note['id']}", "bot", COPY["ask"], meta, at)
    return database.insert_lounge_messages(str(user_id), [row]) or []


def answers_after_note(database: Any, user_id: str) -> list[dict]:
    """What Will adds under a note's "Noted.": the sales question for a sale
    that stalled, else the answer to a worry (N241 items 4 and 5); never
    both. Each is guarded: the note is kept either way."""
    try:
        rows = after_note(database, user_id)
    except Exception as error:  # noqa: BLE001 -- the note is kept either way
        logger.warning("sales framing: note not read user=%s: %s", user_id, error)
        rows = []
    if rows:
        return rows
    try:
        from services.in_control import after_note as answer_worry
        return answer_worry(database, user_id)
    except Exception as error:  # noqa: BLE001 -- the note is kept either way
        logger.warning("worry answer failed user=%s: %s", user_id, error)
        return []


def _asked(database: Any, user_id: str, note_id: str) -> tuple[bool, bool]:
    """(asked, answered) for this note's sales question."""
    rows = database.get_lounge_messages_page(str(user_id), limit=200) or []
    mine = [(r.get("metadata") or {}) for r in rows
            if str((r.get("metadata") or {}).get("sales_note") or "") == note_id]
    return (any(m.get("offer") == OFFER for m in mine),
            any(m.get("sales_step") for m in mine))


def _lines(raw: Any) -> list[str]:
    lines = [" ".join(x.split()) for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    return [x[:_MAX_LINE] for x in lines if x][:_MAX_LINES]


def answer(database: Any, user_id: str, note_id: Any, step: Any) -> list[dict]:
    """A tap on one of the four steps: the step as their bubble, then Will's
    one change to that step (P2). Once per note."""
    from services.lounge_messages import stamp_after, thread_stamp
    if step not in STEPS:
        raise SalesError("INVALID_STEP", "Unknown step.")
    if not enabled(database, user_id):
        raise SalesError("NOT_FOUND", "Not found.", 404)
    note_id = str(note_id or "")
    asked, answered = _asked(database, user_id, note_id) if note_id else (False, False)
    if not asked:
        raise SalesError("NOT_FOUND", "Not found.", 404)
    if answered:
        return []
    notes = database.list_voice_notes(str(user_id), limit=50) or []
    text = next((_note_text(n) for n in notes if str(n.get("id")) == note_id), "")
    lines: list[str] = []
    try:
        lines = _lines(_model(_ONE_CHANGE, f"NOTE: {text}\nSTEP: {STEPS[step]}",
                              user_id, "SPEC_SALES_CHANGE").get("lines"))
    except Exception as error:  # noqa: BLE001 -- the guide's own change instead
        logger.warning("sales framing: no change written user=%s: %s", user_id, error)
    lines = lines or [_CHANGE[step]]
    key = f"{user_id}:sales:{note_id}:{step}"
    at = thread_stamp(database, user_id)
    rows = [_row(f"{key}:me", "user", STEPS[step], {"sales_note": note_id, "sales_step": step}, at)]
    for i, line in enumerate(lines):
        at = stamp_after(at)
        rows.append(_row(f"{key}:{i}", "bot", line, {"sales_note": note_id}, at))
    return database.insert_lounge_messages(str(user_id), rows) or []

