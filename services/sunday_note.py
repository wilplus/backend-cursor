"""The Sunday note (Will learning plan, step 2; founder 2026-10-20, "start
step 2"; the form is the founder's own).

Once a week, on Sunday at 6 pm the founder's local time, and whenever they
ask ("sunday note"), Will writes one case in the chat, in the founder's form:

    CASE AT HAND
    WHAT ONE OF THOSE WAS IT?
    👾 Too much pleasure  👾 Blind spots  👾 Hubris  👾 Wishful thinking
    PRINCIPLES I APPLIED AND HOW I WEIGHED THEM
    REFLECTIONS
    NEW PRINCIPLE ⚜️

It reads the week: the voice notebook, the Lounge thread (their words, Will's
replies, the summaries after each Take), their talk goal, Will's note on
them and the principles they hold in the Life Panel. It names the one bug the
week shows. The footer then asks Old | New (a bug they already knew, or a new
one). When Will has a new principle, it follows as "⚜️ <principle>" with
Not now | Add principle; only "Add principle" puts it among the Life Panel's
active principles (propose, never commit). Never on the recording screens:
the Lounge only.

Founder only: the notebook's ring row and its Yes (``voice_notebook``). The
call to the model runs under the founder's processing authorization, in the
chat's request or, on Sunday, from the worker's sweep
(``pipeline_jobs.run_sweep_loop`` → ``sweep_due`` → ``run_sunday``).
Table: sunday_notes (migration 0485), purged with the account.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: The founder's form and buttons (2026-10-20). No new words without the
#: founder's OK.
HEADINGS = {
    "case": "CASE AT HAND",
    "which": "WHAT ONE OF THOSE WAS IT?",
    "applied": "PRINCIPLES I APPLIED AND HOW I WEIGHED THEM",
    "reflections": "REFLECTIONS",
    "new": "NEW PRINCIPLE ⚜️",
}
PATTERNS = {
    "too_much_pleasure": "👾 Too much pleasure",
    "blind_spots": "👾 Blind spots",
    "hubris": "👾 Hubris",
    "wishful_thinking": "👾 Wishful thinking",
}
COPY = {"old": "Old", "new": "New", "add": "Add principle", "not_now": "Not now",
        "noted": "Noted."}
OFFER = "sunday_note"
PRINCIPLE_OFFER = "sunday_principle"
#: Sunday, from 6 pm local, until the day ends.
_DUE_WEEKDAY, _DUE_HOUR = 6, 18
_SURFACE = "sunday_note"
_NAMESPACE = uuid.UUID("5d2c9a71-0e43-4b8f-9f1a-3c6e2b7d8a14")
_ASKED = re.compile(r"^\s*(#\s*sunday|(my\s+)?sunday\s+note|case of the week)\s*[.!?]*\s*$", re.I)
_DIGIT = re.compile(r"\d|%")
_MAX_INPUT = 14000

_SYSTEM = (
    "You are Will, the private coach in a public-speaking app. Once a week "
    "you write the founder one case about their week, in their own form, "
    "the way Ray Dalio writes a case: the situation, the bug behind it, the "
    "principles used and how they were weighed, what to learn, and one new "
    "principle.\n"
    "You read their private notebook, their chat with you, the summaries "
    "after their Takes, their talk goal, your note on them and the "
    "principles they already hold.\n"
    "Reply with JSON only, these keys:\n"
    "  case: the one case at hand this week, two or three sentences.\n"
    "  pattern: which bug it was, one of too_much_pleasure, blind_spots, "
    "hubris, wishful_thinking, or \"\" when the week does not show one.\n"
    "  why: one sentence, how the week shows that bug.\n"
    "  applied: the principles they applied and how they weighed them, two "
    "or three sentences; name a principle they hold when the week shows it.\n"
    "  reflections: two or three sentences that link the case to their talk "
    "goal and to what they keep doing, helpful or harmful.\n"
    "  new_principle: one short principle in their voice, or \"\" when the "
    "week does not earn one, or it repeats one they hold.\n"
    "Rules: only what the week shows, never invent. Write to them as "
    "\"you\". Plain words, short. No numbers, scores, percentages or "
    "verdicts. No names of other people. If the week is too thin for a "
    "case, say so in case and leave the rest \"\"."
)


class SundayError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zone(name: Optional[str]):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid_zone(name: Any) -> bool:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    if not isinstance(name, str) or not name or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def week_of(now_local: datetime) -> date:
    """The Monday of the local week. Pure."""
    return now_local.date() - timedelta(days=now_local.weekday())


def due_week(now_utc: datetime, zone_name: Optional[str]) -> Optional[date]:
    """The week whose Sunday note is due now (Sunday, 6 pm to midnight in
    their time zone), else None. Pure."""
    local = now_utc.astimezone(_zone(zone_name))
    if local.weekday() == _DUE_WEEKDAY and local.hour >= _DUE_HOUR:
        return week_of(local)
    return None


def _since(week_start: date, zone_name: Optional[str]) -> str:
    return datetime.combine(week_start, time(0), _zone(zone_name)).astimezone(
        timezone.utc).isoformat()


# ── what Will reads ──────────────────────────────────────────────────────

def _thread_lines(database: Any, user_id: str, since: str) -> list[str]:
    rows = database.get_lounge_messages_page(user_id, limit=300) or []
    lines = []
    for r in reversed(rows):  # oldest first
        if str(r.get("client_created_at") or "") < since or not r.get("body"):
            continue
        meta = r.get("metadata") or {}
        if meta.get("offer") in (OFFER, PRINCIPLE_OFFER):
            continue  # an earlier case is not evidence for this one
        who = ("Take summary" if meta.get("summary") else
               "They" if r.get("role") == "user" else "Will")
        lines.append(f"{who}: {str(r['body'])[:600]}")
    return lines


def _principles(user_id: str) -> list[str]:
    try:
        from services import life_store
        return [str(p.get("title") or p.get("body") or "")[:200]
                for p in life_store.principles(user_id, limit=40)]
    except Exception as error:  # noqa: BLE001 -- no Life Panel: none held
        logger.warning("sunday note: principles unread user=%s: %s", user_id, error,
                       exc_info=True)
        return []


def gather(database: Any, user_id: str, since: str) -> str:
    """The week, as the model reads it."""
    from services import speaker_memory
    goal = ((database.get_user_profile(user_id) or {}).get("goal") or "").strip()
    notes = [f"- {str(n.get('created_at') or '')[:10]}: {n.get('text_clean', '')[:800]}"
             for n in database.list_voice_notes(user_id, limit=60)
             if str(n.get("created_at") or "") >= since]
    parts = [
        f"Talk goal: {goal[:300] or '(none set)'}",
        "Principles they hold:\n" + ("\n".join(f"- {p}" for p in _principles(user_id) if p)
                                     or "(none yet)"),
        "Your note on them:\n" + (speaker_memory.note_for(database, user_id) or "(none yet)"),
        "Their notebook this week:\n" + ("\n".join(notes) or "(no notes)"),
        "The chat this week, oldest first:\n"
        + ("\n".join(_thread_lines(database, user_id, since)) or "(nothing)"),
    ]
    return "\n\n".join(parts)[-_MAX_INPUT:]


# ── the note ─────────────────────────────────────────────────────────────

def _clean(value: Any, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())[:limit]
    return "" if _DIGIT.search(text) else text


def render(parsed: dict) -> tuple[str, Optional[str], str]:
    """(the note's text, the bug's key or None, the new principle or "").
    Pure."""
    pattern = parsed.get("pattern") if parsed.get("pattern") in PATTERNS else None
    why = _clean(parsed.get("why"), 300)
    which = [f"{label}: {why}" if key == pattern and why else label
             for key, label in PATTERNS.items()]
    principle = _clean(parsed.get("new_principle"), 300)
    sections = [
        (HEADINGS["case"], _clean(parsed.get("case"))),
        (HEADINGS["which"], "\n".join(which)),
        (HEADINGS["applied"], _clean(parsed.get("applied"))),
        (HEADINGS["reflections"], _clean(parsed.get("reflections"))),
        (HEADINGS["new"], principle),
    ]
    return ("\n\n".join(f"{head}\n{text}" for head, text in sections if text),
            pattern, principle)


def _write(database: Any, user_id: str, since: str) -> Optional[dict]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_SUNDAY_NOTE
    result = chat_complete(spec=SPEC_SUNDAY_NOTE, system=_SYSTEM,
                           user=gather(database, user_id, since),
                           surface=_SURFACE, user_id=user_id)
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) and _clean(parsed.get("case")) else None


def _under_authority(database: Any, user_id: str, key: str, write: Callable[[], Any]):
    """``write`` under the founder's processing authority: the chat's own
    scope when there is one, else (the Sunday sweep) one built the way the
    chat's is. Not authorized: None, no call."""
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, protected_provider_scope,
        scoped_adapter)
    from services.processing_authorization import (
        ProcessingAuthorizationError, ProcessingAuthorizationService)
    authorization = ProcessingAuthorizationService(database)
    if scoped_adapter() is not None or not authorization.enforced:
        return write()
    from services.rings import principal_for_user
    owner = principal_for_user(user_id, database=database)
    if not owner:
        return None
    try:
        principal = authorization.resolve_acquisition_principal(owner, user_id=user_id)
        authorization.require_current(principal, operation="ai_conversation")
    except ProcessingAuthorizationError as error:
        logger.info("sunday note: not authorized user=%s: %s", user_id, error.code)
        return None
    adapter = AuthorizedProviderAdapter(
        database, ProviderCoordinates(principal, None, None), authorization=authorization)
    with protected_provider_scope(adapter, idempotency_prefix=f"sunday-note:{key}"):
        return write()


def _row(key: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": str(uuid.uuid5(_NAMESPACE, key)), "role": role,
            "kind": "text", "body": body, "metadata": meta, "client_created_at": at}


def compose(database: Any, user_id: str, *, source: str, week_start: date,
            zone_name: Optional[str]) -> Optional[dict]:
    """Claim the note, write it and keep it: the stored row with its text,
    or None (a Sunday already claimed, not authorized, or nothing written)."""
    claim = database.insert_sunday_note({
        "user_id": user_id, "week_start": week_start.isoformat(), "source": source})
    if not claim:
        return None
    since = _since(week_start, zone_name)
    parsed = _under_authority(database, user_id, claim["id"],
                              lambda: _write(database, user_id, since))
    if not parsed:
        database.update_sunday_note(claim["id"], {"status": "failed", "updated_at": _now()})
        return None
    body, pattern, principle = render(parsed)
    fields = {"status": "written", "body": body, "pattern": pattern,
              "new_principle": principle or None, "updated_at": _now()}
    database.update_sunday_note(claim["id"], fields)
    return {**claim, **fields}


def note_meta(note: dict) -> dict:
    return {"offer": OFFER, "sunday_note_id": str(note["id"])}


def run_sunday(user_id: str, week_start_iso: str) -> None:
    """The worker's job: Sunday's note, once per week, into the Lounge."""
    from services.db import db
    from services.lounge_messages import thread_stamp
    from services import voice_notebook
    try:
        if not voice_notebook.enabled(db, user_id):
            return
        consent = db.get_voice_notebook_consent(user_id) or {}
        if consent.get("decision") != "yes":
            return
        note = compose(db, user_id, source="sunday",
                       week_start=date.fromisoformat(week_start_iso),
                       zone_name=consent.get("time_zone"))
        if not note:
            return
        db.insert_lounge_messages(user_id, [_row(
            f"{user_id}:note:{note['id']}", "bot", note["body"], note_meta(note),
            thread_stamp(db, user_id))])
    except Exception as error:  # noqa: BLE001 -- next Sunday tries again
        logger.warning("sunday note failed user=%s: %s", user_id, error, exc_info=True)


def sweep_due(database: Any = None, now: Optional[datetime] = None) -> int:
    """Each minute, from the worker's sweep: enqueue the Sunday note for
    whoever said Yes to the notebook and whose Sunday 6 pm has come. Cheap:
    one read of a table of a few rows; the job itself claims the week."""
    from services import job_queue
    if database is None:
        from services.db import db as database
    moment = now or datetime.now(timezone.utc)
    queued = 0
    for row in database.list_voice_notebook_consents() or []:
        week = due_week(moment, row.get("time_zone"))
        if not week or database.get_sunday_note_for_week(str(row["user_id"]), week.isoformat()):
            continue
        if job_queue.enqueue("services.sunday_note.run_sunday", str(row["user_id"]),
                             week.isoformat(),
                             rq_job_id=f"sunday-note-{row['user_id']}-{week.isoformat()}"):
            queued += 1
    return queued


# ── the chat and the footer ──────────────────────────────────────────────

def _newest_bot(database: Any, user_id: str) -> dict:
    rows = database.get_lounge_messages_page(str(user_id), limit=4) or []
    return next((r for r in rows if r.get("role") == "bot"), None) or {}


def chat_turn(database: Any, user_id: str, question: str) -> Optional[dict]:
    """The chat's intercept: "sunday note" writes one now; "Old"/"New" or
    "Add principle"/"Not now" typed under the open ask count as the tap.
    None for anything else, and for anyone without the notebook."""
    from services import voice_notebook
    text = (question or "").strip()
    asked = bool(_ASKED.match(text))
    said = text.rstrip(".!").lower()
    if not asked and said not in ("old", "new", "add principle", "not now"):
        return None
    if not voice_notebook.enabled(database, user_id) or not voice_notebook.consented(
            database, user_id):
        return None
    if asked:
        consent = database.get_voice_notebook_consent(str(user_id)) or {}
        zone = consent.get("time_zone")
        local = datetime.now(timezone.utc).astimezone(_zone(zone))
        note = compose(database, str(user_id), source="asked",
                       week_start=week_of(local), zone_name=zone)
        if not note:
            return None  # Will answers as usual
        return {"answer": note["body"], "row_metadata": note_meta(note)}
    meta = _newest_bot(database, user_id).get("metadata") or {}
    note_id = meta.get("sunday_note_id")
    if meta.get("offer") == OFFER and said in ("old", "new"):
        return _as_reply(mark(database, str(user_id), str(note_id), said, write=False))
    if meta.get("offer") == PRINCIPLE_OFFER and said in ("add principle", "not now"):
        choice = "add" if said == "add principle" else "not_now"
        return _as_reply(principle(database, str(user_id), str(note_id), choice, write=False))
    return None


def _as_reply(rows: list[dict]) -> Optional[dict]:
    """A typed answer: the chat stores their words; the bot's row is the
    reply (empty when the tap writes none, which hands the turn on)."""
    bot = next((r for r in rows if r["role"] == "bot"), None)
    if not bot:
        return None
    return {"answer": bot["body"], "row_metadata": bot.get("metadata") or {}}


def _owned(database: Any, user_id: str, note_id: str) -> dict:
    note = database.get_sunday_note(user_id, note_id)
    if not note or note.get("status") != "written":
        raise SundayError("NOT_FOUND", "Not found.", 404)
    return note


def mark(database: Any, user_id: str, note_id: str, choice: str, *,
         write: bool = True) -> list[dict]:
    """Old or New for the week's bug. Then, when Will has a new principle,
    "⚜️ <principle>" with Not now | Add principle. A repeat tap writes nothing."""
    if choice not in ("old", "new"):
        raise SundayError("INVALID_CHOICE", "Unknown answer.")
    note = _owned(database, user_id, note_id)
    if note.get("pattern_known"):
        return []
    database.update_sunday_note(note_id, {"pattern_known": choice, "updated_at": _now()})
    from services.lounge_messages import stamp_after, thread_stamp
    at = thread_stamp(database, user_id)
    rows = [_row(f"{note_id}:{choice}", "user", COPY[choice], {"sunday_note": choice}, at)]
    if note.get("new_principle"):
        rows.append(_row(f"{note_id}:principle", "bot", f"⚜️ {note['new_principle']}",
                         {"offer": PRINCIPLE_OFFER, "sunday_note_id": note_id},
                         stamp_after(at)))
    else:
        rows.append(_row(f"{note_id}:noted", "bot", COPY["noted"],
                         {"sunday_note": "noted"}, stamp_after(at)))
    if not write:
        return rows  # typed: the chat stores their turn and the reply itself
    return database.insert_lounge_messages(user_id, rows) or []


def principle(database: Any, user_id: str, note_id: str, choice: str, *,
              write: bool = True) -> list[dict]:
    """Add principle: it joins the Life Panel's active principles (the
    founder's own approval) and is answered "Noted."; Not now keeps it out.
    Either way the reply is "Noted.". A repeat tap writes nothing."""
    if choice not in ("add", "not_now"):
        raise SundayError("INVALID_CHOICE", "Unknown answer.")
    note = _owned(database, user_id, note_id)
    line = note.get("new_principle")
    if not line or note.get("principle_item_id") or note.get("principle_declined"):
        return []
    from services.lounge_messages import stamp_after, thread_stamp
    at = thread_stamp(database, user_id)
    rows = [_row(f"{note_id}:{choice}", "user", COPY[choice], {"sunday_note": choice}, at)]
    if choice == "add":
        item = _add_principle(user_id, line)
        if not item:
            raise SundayError("V2_ERROR", "Failed to add the principle", 500)
        database.update_sunday_note(note_id, {"principle_item_id": item["id"],
                                              "updated_at": _now()})
    else:
        database.update_sunday_note(note_id, {"principle_declined": True,
                                              "updated_at": _now()})
    rows.append(_row(f"{note_id}:noted", "bot", COPY["noted"],
                     {"sunday_note": choice}, stamp_after(at)))
    if not write:
        return rows
    return database.insert_lounge_messages(user_id, rows) or []


def _add_principle(user_id: str, line: str) -> Optional[dict]:
    from services import life_panel as lp
    from services import life_store
    return life_store.insert_item(user_id, {
        "kind": "principle", "title": line[:500], "body": line, "status": "active",
        "order_key": lp.next_order_key(life_store.principles(user_id))})


def latest_line(database: Any, user_id: str) -> str:
    """Last week's case for Will's chat prompt, one line; "" without one.
    Never raises: the notebook's notes are read either way."""
    try:
        note = database.latest_sunday_note(str(user_id))
    except Exception as error:  # noqa: BLE001 -- no case: the notes still count
        logger.warning("sunday note: last case unread user=%s: %s", user_id, error,
                       exc_info=True)
        return ""
    if not note or note.get("status") != "written" or not note.get("pattern"):
        return ""
    known = {"old": " (a bug they already knew)", "new": " (a new bug)"}.get(
        note.get("pattern_known") or "", "")
    return (f"  • Their last Sunday case named {PATTERNS[note['pattern']][2:].lower()}"
            f"{known}.\n")
