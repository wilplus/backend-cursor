"""The Sunday note as a lens (Will learning plan, step 2; locked 2026-10-26,
N158, N170; rules: frontend docs/flows/principles.md §1 L; prototype
https://claude.ai/artifact/Bt2YEZLKhu9fLTA1deWTvo).

On Sunday from 6 pm the founder's local time, once, Will brings a case by
itself when the last seven days of # notes show a pattern, and not when a
case was already shown in those seven days; on any day, when asked in any
words, Will looks (L1). The case comes only from the # notes of the last
seven days; the talk goal and the principles held are context, never
evidence. With nothing to find, an asked look says so in one bubble; Sunday
by itself never does.

In the Lounge (L2): "We spotted a pattern!" and the case in one sentence,
with Not now | Investigate. The lens (L3 to L7) asks which of the four bugs
it was (or a new one), which held principle was in place (the two most
likely, or None yet), the speaker's reflection (never Will's), then Will's
new principle: Accept, Edit or Not now. Only Accept or an edited Add puts it
among the Life Panel's active principles (propose, never commit). Every
question and answer is a row of the one Lounge thread (L8), so the lens and
the Lounge show the same rows and the lens reopens where it stands.

A sales pattern (N241 P3, signed N258): when the week's notes show sales
stalling and the person has the ring row ``sales_framing``, the case is
marked ``kind: "sales"`` and the lens asks "Which step was it?" with the
sale's four steps (or their own new one) in place of the four bugs; then the
principle held, the reflection, and a principle about the process.

Founder only: the notebook's ring row and its Yes (``voice_notebook``). The
model call runs under the founder's processing authorization, in the chat's
request or, on Sunday, from the worker's sweep
(``pipeline_jobs.run_sweep_loop`` → ``sweep_due`` → ``run_sunday``).
Table: sunday_notes (migration 0486), purged with the account.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: The four bugs (the founder's own form, 2026-10-20).
PATTERNS = {
    "too_much_pleasure": "👾 Too much pleasure",
    "blind_spots": "👾 Blind spots",
    "hubris": "👾 Hubris",
    "wishful_thinking": "👾 Wishful thinking",
}
#: The sale's four steps, for a sales pattern (N241 P3, signed N258).
SALES_STEPS = {
    "opening": "🚪 The opening",
    "discovery": "🔍 Discovery",
    "offer": "🎁 The offer",
    "follow_up": "📨 The follow-up",
}
#: The signed words (N158, N170). No new words without the founder's OK.
COPY = {
    "head": "We spotted a pattern!",
    "no_notes": "There are no # notes from the last seven days yet.",
    "nothing": "Nothing stands out in your notes from the last seven days yet.",
    "which": "What one of those was it?",
    "which_step": "Which step was it?",
    "applied": "Did you have a principle in place already?",
    "none_yet": "None yet",
    "reflections": "Reflections: what do you take from this?",
    "skip": "Skip",
    "suggests": "Will suggests a new principle:",
    "accept": "Accept",
    "not_now": "Not now",
    "added": "Noted. Added to your principles.",
    "noted": "Noted.",
}
OFFER = "sunday_note"
#: The lens's steps, in order (L4 to L7).
STEPS = ("bug", "applied", "reflection", "principle")
#: Sunday, from 6 pm local, until the day ends.
_DUE_WEEKDAY, _DUE_HOUR = 6, 18
_WINDOW = timedelta(days=7)
_SURFACE = "sunday_note"
_NAMESPACE = uuid.UUID("5d2c9a71-0e43-4b8f-9f1a-3c6e2b7d8a14")
#: Asked by its name: no model call needed to know.
_ASKED = re.compile(r"^\s*(#\s*sunday|(my\s+)?sunday\s+note|case of the week)\s*[.!?]*\s*$", re.I)
#: The cheap pre-gate before the meaning is classified: a question that may be
#: about what keeps happening (L1, "goes by the meaning").
_MAYBE = re.compile(r"pattern|sunday|niedziel|wzorz|trip|keep[s]?\b|again|repeat|habit|"
                    r"notice|same (mistake|thing)|what.*(my )?notes|stuck|holding me back|"
                    r"powtarza|ciągle|znowu", re.I)
_DIGIT = re.compile(r"\d|%")
_MAX_INPUT = 14000

_SYSTEM = (
    "You are Will, the private coach in a public-speaking app. You read one "
    "person's own short notes from the last seven days and look for one "
    "pattern in what they did: the same kind of slip more than once, or one "
    "clear case of it.\n"
    "You get, numbered, the principles they already hold, and their talk "
    "goal: context only, never evidence. The notes are the only evidence.\n"
    "Reply with JSON only, these keys:\n"
    "  case: the pattern in ONE sentence, to them as \"you\", in the "
    "language of the notes; \"\" when the notes do not show one. Never "
    "invent.\n"
    "  principles: the numbers of at most two held principles most likely "
    "to apply to this case, most likely first; [] when none fits.\n"
    "  new_principle: one short principle in their voice that the case "
    "teaches, or \"\" when it repeats one they hold.\n"
    "  kind: \"sales\" when the pattern is sales of theirs stalling or being "
    "lost (calls, deals, clients, proposals), else \"self\". For a sales "
    "pattern, the case and the principle are about the sale's process (the "
    "opening, discovery, the offer, the follow-up), never about the person.\n"
    "Plain words. No numbers or digits, no scores, percentages or verdicts. "
    "No names of other people."
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


# ── what Will reads: the # notes of the last seven days (L1) ────────────

def _held(user_id: str) -> list[dict]:
    """The principles they hold, as context: ``[{"id", "title"}]``."""
    try:
        from services import life_store
        return [{"id": str(p["id"]), "title": str(p.get("title") or p.get("body") or "")[:200]}
                for p in life_store.principles(user_id, limit=40) if p.get("id")]
    except Exception as error:  # noqa: BLE001 -- no Life Panel: none held
        logger.warning("sunday note: principles unread user=%s: %s", user_id, error,
                       exc_info=True)
        return []


def notes_since(database: Any, user_id: str, now: datetime) -> list[dict]:
    """The # notes of the last seven days, not the calendar week (N170)."""
    since = (now - _WINDOW).isoformat()
    return [n for n in database.list_voice_notes(user_id, limit=60)
            if str(n.get("created_at") or "") >= since and n.get("text_clean")]


def gather(database: Any, user_id: str, notes: list[dict], held: list[dict]) -> str:
    """The notes, as the model reads them: the evidence, then the context."""
    goal = ((database.get_user_profile(user_id) or {}).get("goal") or "").strip()
    parts = [
        "Their notes, oldest first:\n" + "\n".join(
            f"- {str(n.get('created_at') or '')[:10]}: {str(n['text_clean'])[:800]}"
            for n in notes),
        "Principles they hold:\n" + ("\n".join(f"{i + 1}. {p['title']}" for i, p in
                                                 enumerate(held)) or "(none yet)"),
        f"Talk goal: {goal[:300] or '(none set)'}",
    ]
    return "\n\n".join(parts)[-_MAX_INPUT:]


def _clean(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())[:limit]
    return "" if _DIGIT.search(text) else text


def _write(database: Any, user_id: str, notes: list[dict], held: list[dict]) -> Optional[dict]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_SUNDAY_NOTE
    result = chat_complete(spec=SPEC_SUNDAY_NOTE, system=_SYSTEM,
                           user=gather(database, user_id, notes, held),
                           surface=_SURFACE, user_id=user_id)
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else None


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


def _likely(parsed: dict, held: list[dict]) -> list[dict]:
    """The two held principles most likely to apply (L5), from the model's
    numbers; never one it made up."""
    raw = parsed.get("principles")
    picked: list = raw if isinstance(raw, list) else []
    return [held[i - 1] for i in dict.fromkeys(picked)
            if isinstance(i, int) and 1 <= i <= len(held)][:2]


def compose(database: Any, user_id: str, *, source: str, now: datetime,
            zone_name: Optional[str]) -> tuple[str, Optional[dict]]:
    """Look at the last seven days: ``("no_notes", None)``, ``("nothing",
    None)``, ``("shown", None)`` (Sunday only: a case was already shown in
    those days) or ``("case", note)`` with the note kept and its likely
    principles."""
    notes = notes_since(database, user_id, now)
    if not notes:
        return "no_notes", None
    if source == "sunday":
        last = database.latest_sunday_note(user_id) or {}
        if str(last.get("created_at") or "") >= (now - _WINDOW).isoformat():
            return "shown", None
    week = week_of(now.astimezone(_zone(zone_name)))
    claim = database.insert_sunday_note({
        "user_id": user_id, "week_start": week.isoformat(), "source": source})
    if not claim:
        return "shown", None
    held = _held(user_id)
    parsed = _under_authority(database, user_id, claim["id"],
                              lambda: _write(database, user_id, notes, held)) or {}
    case = _clean(parsed.get("case"), 400)
    if not case:
        database.update_sunday_note(claim["id"], {"status": "failed", "updated_at": _now()})
        return "nothing", None
    fields = {"status": "written", "body": case, "updated_at": _now(),
              "new_principle": _clean(parsed.get("new_principle"), 300) or None}
    database.update_sunday_note(claim["id"], fields)
    return "case", {**claim, **fields, "likely": _likely(parsed, held),
                    "kind": _kind(database, user_id, parsed)}


def _kind(database: Any, user_id: str, parsed: dict) -> str:
    """"sales" for a sales pattern, only with the ring row ``sales_framing``
    (N241 P3); "self" otherwise, the four bugs as before."""
    if parsed.get("kind") != "sales":
        return "self"
    from services import rings
    on = rings.feature_is_on_for_user("sales_framing", user_id, database=database)
    return "sales" if on else "self"


def _head_meta(note: dict) -> dict:
    return {"sunday_note_id": str(note["id"]), "sunday_step": "head"}


def case_row(user_id: str, note: dict, at: str) -> dict:
    """The case in one sentence, with Not now | Investigate (L2)."""
    meta = {"offer": OFFER, "sunday_note_id": str(note["id"]), "sunday_step": "case",
            "likely": note.get("likely") or []}
    if note.get("kind") == "sales":
        meta["kind"] = "sales"
    return _row(f"{note['id']}:case", "bot", note["body"], meta, at)


def run_sunday(user_id: str, now_iso: str) -> None:
    """The worker's job: Sunday's look, once, into the Lounge only when the
    notes show a pattern; nothing otherwise (L1)."""
    from services.db import db
    from services.lounge_messages import stamp_after, thread_stamp
    from services import voice_notebook
    try:
        if not voice_notebook.enabled(db, user_id):
            return
        consent = db.get_voice_notebook_consent(user_id) or {}
        if consent.get("decision") != "yes":
            return
        found, note = compose(db, user_id, source="sunday",
                              now=_moment(now_iso), zone_name=consent.get("time_zone"))
        if found != "case" or not note:
            return
        at = thread_stamp(db, user_id)
        db.insert_lounge_messages(user_id, [
            _row(f"{note['id']}:head", "bot", COPY["head"], _head_meta(note), at),
            case_row(user_id, note, stamp_after(at))])
    except Exception as error:  # noqa: BLE001 -- next Sunday tries again
        logger.warning("sunday note failed user=%s: %s", user_id, error, exc_info=True)


def _moment(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:  # a week_start from before the lens: the day's end
        moment = datetime.combine(date.fromisoformat(value) + timedelta(days=6),
                                  datetime.max.time())
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def sweep_due(database: Any = None, now: Optional[datetime] = None) -> int:
    """Each minute, from the worker's sweep: enqueue Sunday's look for whoever
    said Yes to the notebook and whose Sunday 6 pm has come. Cheap: one read
    of a table of a few rows; the job itself claims the week."""
    from services import job_queue, plan_flow
    if database is None:
        from services.db import db as database
    moment = now or datetime.now(timezone.utc)
    queued = 0
    for row in database.list_voice_notebook_consents() or []:
        week = due_week(moment, row.get("time_zone"))
        if not week or database.get_sunday_note_for_week(str(row["user_id"]), week.isoformat()):
            continue
        if plan_flow.onboarding(database, str(row["user_id"])):
            continue  # it waits while the person is onboarded (N243)
        if job_queue.enqueue("services.sunday_note.run_sunday", str(row["user_id"]),
                             moment.isoformat(),
                             rq_job_id=f"sunday-note-{row['user_id']}-{week.isoformat()}"):
            queued += 1
    return queued


# ── asked in the chat, in any words (L1) ─────────────────────────────────

_ASK_SYSTEM = (
    "Decide whether this message asks to look at the person's own notes for "
    "a pattern, a habit or what keeps tripping them up (for example: \"do you "
    "see a pattern?\", \"what keeps tripping me up?\", \"sunday note\"). A "
    "question about speaking technique, a Take or anything else is not.\n"
    "Return JSON: {\"asks\": true or false}."
)


def _asks(question: str, user_id: str) -> bool:
    if _ASKED.match(question):
        return True
    if not _MAYBE.search(question):
        return False
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_LIFE_GOAL_ASK
        result = chat_complete(spec=SPEC_LIFE_GOAL_ASK, system=_ASK_SYSTEM,
                               user=question[:600], surface=_SURFACE, user_id=str(user_id))
        parsed = getattr(result, "parsed", None) if result else None
        return isinstance(parsed, dict) and parsed.get("asks") is True
    except Exception as error:  # noqa: BLE001 -- the chat answers as usual
        logger.warning("sunday note: ask unread user=%s: %s", user_id, error, exc_info=True)
        return False


def chat_turn(database: Any, user_id: str, question: str) -> Optional[dict]:
    """The chat's intercept: an ask for the case, in any words. The reply is
    "We spotted a pattern!" (the case row follows it, ``after_head``) or, with
    nothing to find, the one grey bubble that says so. None for anything
    else, for a # note, and for anyone without the notebook."""
    from services import voice_notebook
    text = (question or "").strip()
    if not text or text.startswith("#") and not _ASKED.match(text):
        return None
    if not voice_notebook.enabled(database, user_id) or not voice_notebook.consented(
            database, user_id):
        return None
    from services import plan_flow
    if plan_flow.onboarding(database, user_id):
        return None  # the principles wait while the person is onboarded (N243)
    if not _asks(text, user_id):
        return None
    consent = database.get_voice_notebook_consent(str(user_id)) or {}
    found, note = compose(database, str(user_id), source="asked",
                          now=datetime.now(timezone.utc), zone_name=consent.get("time_zone"))
    if found == "case" and note:
        return {"answer": COPY["head"], "row_metadata": _head_meta(note),
                "case": note}
    return {"answer": COPY["no_notes" if found == "no_notes" else "nothing"],
            "row_metadata": {"sunday_empty": found}}


def after_head(database: Any, user_id: str, note: dict) -> bool:
    """Under the chat's "We spotted a pattern!": the case row (L2)."""
    from services.lounge_messages import thread_stamp
    return bool(database.insert_lounge_messages(
        str(user_id), [case_row(str(user_id), note, thread_stamp(database, user_id))]))


# ── the lens: one thread, step by step (L3 to L8) ────────────────────────

def _owned(database: Any, user_id: str, note_id: str) -> dict:
    note = database.get_sunday_note(user_id, note_id)
    if not note or note.get("status") != "written":
        raise SundayError("NOT_FOUND", "Not found.", 404)
    return note


def _rows_of(database: Any, user_id: str, note_id: str) -> list[dict]:
    """The note's rows in the thread, oldest first."""
    rows = database.get_lounge_messages_page(str(user_id), limit=300) or []
    return [r for r in reversed(rows)
            if (r.get("metadata") or {}).get("sunday_note_id") == str(note_id)]


def _answered(rows: list[dict]) -> set:
    return {(r.get("metadata") or {}).get("sunday_step") for r in rows if r.get("role") == "user"}


def state(database: Any, user_id: str, note_id: str) -> dict:
    """The lens as it stands: the case, the two likely principles, Will's new
    principle, the rows so far and the step it waits on ("done" at the end,
    "closed" after Not now in the Lounge)."""
    note = _owned(database, user_id, note_id)
    rows = _rows_of(database, user_id, note_id)
    done = _answered(rows)
    case = next((r for r in rows if (r.get("metadata") or {}).get("sunday_step") == "case"), {})
    likely = (case.get("metadata") or {}).get("likely") or []
    kind = "sales" if (case.get("metadata") or {}).get("kind") == "sales" else "self"
    if "dismiss" in done:
        step = "closed"
    else:
        step = next((s for s in STEPS if s not in done), "done")
        if step == "principle" and not note.get("new_principle"):
            step = "done"
    return {"id": str(note["id"]), "case": note.get("body") or "", "likely": likely, "kind": kind,
            "new_principle": note.get("new_principle"), "step": step,
            "rows": [{"role": r["role"], "body": r["body"],
                      "step": (r.get("metadata") or {}).get("sunday_step")}
                     for r in rows if (r.get("metadata") or {}).get("sunday_step")
                     not in ("head", "case")]}


def _say(note_id: str, step: str, role: str, body: str, at: str) -> dict:
    return _row(f"{note_id}:{step}:{role}", role, body,
                {"sunday_note_id": str(note_id), "sunday_step": step}, at)


def _bug_words(value: str, kind: str = "self") -> tuple[str, Optional[str]]:
    """The answer's words, and the bug's key to keep (none for a sale's step
    or their own name)."""
    if kind == "sales" and value in SALES_STEPS:
        return SALES_STEPS[value], None
    if kind != "sales" and value in PATTERNS:
        return PATTERNS[value], value
    name = " ".join(value.split())[:80]
    if not name:
        raise SundayError("EMPTY", "No words.")
    return (name if kind == "sales" else f"👾 {name}"), None


def answer(database: Any, user_id: str, note_id: str, step: str, value: Any = None) -> dict:
    """One tap in the lens (or Not now under the case), kept as rows of the
    thread: the answer as the speaker's bubble, then Will's next question.
    A step already answered, or out of turn, writes nothing."""
    from services.lounge_messages import stamp_after, thread_stamp
    now = state(database, user_id, note_id)
    expected = {"open": now["step"] == "bug", "dismiss": now["step"] == "bug",
                **{s: now["step"] == s for s in STEPS}}
    if step not in expected:
        raise SundayError("INVALID_STEP", "Unknown step.")
    if not expected[step] or (step == "open" and any(r["step"] == "open" for r in now["rows"])):
        return now
    # Their own words are kept as they wrote them, numbers too.
    text = " ".join(value.split())[:2000] if isinstance(value, str) else ""
    at = thread_stamp(database, user_id)
    rows: list[dict] = []
    if step == "dismiss":
        rows = [_say(note_id, "dismiss", "user", COPY["not_now"], at),
                _say(note_id, "dismiss", "bot", COPY["noted"], stamp_after(at))]
    elif step == "open":
        rows = [_say(note_id, "open", "bot",
                     COPY["which_step" if now["kind"] == "sales" else "which"], at)]
    elif step == "bug":
        words, key = _bug_words(text, now["kind"])
        if key:
            database.update_sunday_note(note_id, {"pattern": key, "updated_at": _now()})
        rows = [_say(note_id, "bug", "user", words, at),
                _say(note_id, "bug", "bot", COPY["applied"], stamp_after(at))]
    elif step == "applied":
        held = next((p for p in now["likely"] if p.get("id") == str(value)), None)
        words = f"⚜️ {held['title']}" if held else COPY["none_yet"]
        rows = [_say(note_id, "applied", "user", words, at),
                _say(note_id, "applied", "bot", COPY["reflections"], stamp_after(at))]
    elif step == "reflection":
        rows = [_say(note_id, "reflection", "user", text or COPY["skip"], at)]
        if now["new_principle"]:
            later = stamp_after(at)
            rows += [_say(note_id, "reflection", "bot", COPY["suggests"], later),
                     _row(f"{note_id}:suggested", "bot", f"⚜️ {now['new_principle']}",
                          {"sunday_note_id": str(note_id), "sunday_step": "suggested"},
                          stamp_after(later))]
        else:
            rows.append(_say(note_id, "reflection", "bot", COPY["noted"], stamp_after(at)))
    else:
        rows = _principle_rows(database, user_id, now, value, at)
    database.insert_lounge_messages(str(user_id), rows)
    return state(database, user_id, note_id)


def _principle_rows(database: Any, user_id: str, now: dict, value: Any, at: str) -> list[dict]:
    """Accept, Add principle (edited) or Not now (L7)."""
    from services.lounge_messages import stamp_after
    note_id = now["id"]
    choice = value.get("choice") if isinstance(value, dict) else value
    if choice == "not_now":
        database.update_sunday_note(note_id, {"principle_declined": True, "updated_at": _now()})
        return [_say(note_id, "principle", "user", COPY["not_now"], at),
                _say(note_id, "principle", "bot", COPY["noted"], stamp_after(at))]
    edited = " ".join(str(value.get("text") or "").split())[:300] if isinstance(value, dict) else ""
    if choice not in ("accept", "edit") or (choice == "edit" and not edited):
        raise SundayError("INVALID_CHOICE", "Unknown answer.")
    line = edited or now["new_principle"]
    item = _add_principle(user_id, line)
    if not item:
        raise SundayError("V2_ERROR", "Failed to add the principle", 500)
    database.update_sunday_note(note_id, {"principle_item_id": item["id"], "new_principle": line,
                                          "updated_at": _now()})
    return [_say(note_id, "principle", "user",
                 COPY["accept"] if choice == "accept" else f"⚜️ {line}", at),
            _say(note_id, "principle", "bot", COPY["added"], stamp_after(at))]


def _add_principle(user_id: str, line: str) -> Optional[dict]:
    from services import life_panel as lp
    from services import life_store
    return life_store.insert_item(user_id, {
        "kind": "principle", "title": line[:500], "body": line, "status": "active",
        "order_key": lp.next_order_key(life_store.principles(user_id))})


def latest_line(database: Any, user_id: str) -> str:
    """The last case for Will's chat prompt, one line; "" without one.
    Never raises: the notebook's notes are read either way."""
    try:
        note = database.latest_sunday_note(str(user_id))
    except Exception as error:  # noqa: BLE001 -- no case: the notes still count
        logger.warning("sunday note: last case unread user=%s: %s", user_id, error,
                       exc_info=True)
        return ""
    if not note or note.get("status") != "written" or not note.get("body"):
        return ""
    bug = f" They named it {PATTERNS[note['pattern']][2:].lower()}." if note.get(
        "pattern") in PATTERNS else ""
    return f"  • Their last Sunday case: {str(note['body'])[:300]}{bug}\n"
