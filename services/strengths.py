"""Strengths (Linear WIL-112; founder 2026-10-28, N241 items 1 to 3; words
and choices signed N258; rules: frontend docs/flows/principles.md §1 N;
prototype https://claude.ai/artifact/1hfLf8mCif8pgC1X1Z6caJ, scenes 1 to 5).

  * Under a # note's "Noted.", one read of the note (``after_note``):
      - a kept strength at work in it: "That's your 💪 {strength} again." once,
        and the note is kept under that strength (N3);
      - else, a positive trait that shows in this note and on another day (a
        note, or the life goals answer "What fits your nature and
        strengths?"): "We spotted a strength!" and what the notes show, once,
        with Not now | Look (the offer ``strengths``, N2). Look opens the
        lens (the frontend's): the notes quoted with their dates, "Will
        suggests a strength:", Accept, Edit or Not now (``decide``). Never
        invented; one suggestion open at a time;
      - a talk date the note names is kept (N4).
  * The first time the Lounge opens on the day before a talk (the plan's
    deadline or a date a note named), one kept strength comes back, quoting
    the note it came from (``today``, N4). No date, no reminder.
  * The Life Panel's Strengths pill lists them with their notes (``listing``);
    only the person archives one, and it stays in the history (``archive``,
    N5). Will never says a strength did not show.

Kept in the Life Panel's store (services/life_store.py: strengths,
strength_notes, talk_dates; migration your_why_and_strengths_are_kept).
Ring row ``strengths``, ring 5. Never under a crisis reply, never while
onboarded (N243); private, never shown to a coach (N182).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

FEATURE = "strengths"
_SURFACE = "strengths"
_NAMESPACE = uuid.UUID("4e8b1d27-9c3a-4f60-b5e2-7a1c0d9f3b65")
OFFER = "strengths"
MARK = "💪"
#: The signed words (N258). No new words without the founder's OK.
COPY = {
    "head": "We spotted a strength!",
    "again": "That's your 💪 {title} again.",
    "added": "Noted. Added to your strengths.",
    "noted": "Noted.",
    "not_now": "Not now",
    "accept": "Accept",
    "talk": "Your talk is tomorrow.",
    "remember": "Remember your 💪 {title}:",
    "goals_answer": "Your life goals answer",
}
_LOOKBACK = timedelta(days=60)
_MAX_NOTE = 1200
_MAX_TITLE = 80
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")

_READ = """One person keeps short private notes (# notes). You get their
newest note, their other notes with their dates, numbered, possibly their own
answer to "What fits your nature and strengths?" as number 0, the strengths
they already keep, numbered as K1, K2, ..., and strengths they already said
"not now" to. Today's date is given.

Answer three things about the NEWEST note only:
1. kept: the K number of a kept strength clearly at work in the newest note,
   or null.
2. suggest: only when kept is null. A positive trait of theirs that shows in
   the newest note AND in at least one other numbered note on a different day
   (or answer 0). Not one they keep or said not now to. Never invent: when it
   does not clearly show twice, null. Else {"title": "<two to five words,
   plain, no emoji>", "sentence": "<one short sentence to them as you, what
   the notes show, no numbers>", "others": [<the other note numbers or 0>]}.
3. talk_on: the date (YYYY-MM-DD) of a talk, pitch or presentation the newest
   note names, worked out from today's date, or null.

Return JSON only: {"kept": ..., "suggest": ..., "talk_on": ...}."""


class StrengthError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def enabled(database: Any, user_id: Any) -> bool:
    """Does this person have strengths? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)


def _waits(database: Any, user_id: Any) -> bool:
    from services import plan_flow
    return plan_flow.onboarding(database, user_id)


def _row(key: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": str(uuid.uuid5(_NAMESPACE, key)), "role": role,
            "kind": "text", "body": body, "metadata": meta, "client_created_at": at}


def _clip(value: Any, limit: int = _MAX_NOTE) -> str:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text[:limit]


def _text(note: dict) -> str:
    return _clip(note.get("text_clean")).lstrip("#").strip()


def _day(raw: Any) -> str:
    return str(raw or "")[:10]


def _label(on: str) -> str:
    try:
        d = date.fromisoformat(on)
    except ValueError:
        return on
    return f"{d.day} {_MONTHS[d.month - 1]}"


def _today(database: Any, user_id: str, now: Optional[datetime] = None) -> date:
    from services.sunday_note import _zone
    now = now or datetime.now(timezone.utc)
    zone_name = (database.get_voice_notebook_consent(str(user_id)) or {}).get("time_zone")
    return now.astimezone(_zone(zone_name)).date()


def _model(user: str, user_id: str) -> dict:
    from services.llm import chat_complete
    from services.llm_config import SPEC_STRENGTHS_READ
    result = chat_complete(spec=SPEC_STRENGTHS_READ, system=_READ, user=user,
                           surface=_SURFACE, user_id=str(user_id))
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else {}


def _goals_answer(user_id: str) -> Optional[dict]:
    """Their own answer to "What fits your nature and strengths?" (M4), with
    the day the goal was set: it counts as one note (N2)."""
    from services import life_store
    for goal in life_store.list_goals(str(user_id)):
        said = _clip(((goal.get("ladder") or {}).get("answers") or {}).get("nature"))
        if said:
            return {"body": said, "on": _day(goal.get("created_at"))}
    return None


def after_note(database: Any, user_id: str) -> list[dict]:
    """Under the newest # note's "Noted.": "That's your … again." for a kept
    strength at work, else a suggestion when a trait shows on two days; a
    talk date the note names is kept. [] most of the time."""
    from services import life_store
    from services.voice_notebook import _crisis
    if not enabled(database, user_id) or _waits(database, user_id):
        return []
    notes = database.list_voice_notes(str(user_id), limit=60) or []
    newest = notes[-1] if notes else {}
    text = _text(newest)
    if not text or not newest.get("id") or _crisis(text):
        return []
    since = (datetime.now(timezone.utc) - _LOOKBACK).date().isoformat()
    others = [n for n in notes[:-1] if _text(n) and _day(n.get("created_at")) >= since]
    strengths = life_store.list_strengths(str(user_id))
    kept = [s for s in strengths if s.get("status") == "kept"]
    declined = [s["title"] for s in strengths if s.get("status") in ("not_now", "suggested")]
    answer = _goals_answer(user_id)
    lines = [f"TODAY: {_today(database, user_id).isoformat()}",
             f"NEWEST NOTE ({_day(newest.get('created_at'))}): {text}"]
    lines += [f"{i + 1}. ({_day(n.get('created_at'))}) {_text(n)}" for i, n in enumerate(others)]
    if answer:
        lines.append(f"0. ({answer['on']}) {answer['body']}")
    lines += [f"K{i + 1}. {s['title']}" for i, s in enumerate(kept)]
    if declined:
        lines.append("NOT NOW: " + "; ".join(declined))
    parsed = _model("\n".join(lines), user_id)
    _keep_talk(user_id, parsed.get("talk_on"), newest)
    again = _again(database, user_id, parsed.get("kept"), kept, newest, text)
    if again:
        return again
    if any(s.get("status") == "suggested" for s in strengths):
        return []  # one suggestion open at a time
    return _suggest(database, user_id, parsed.get("suggest"), newest, text, others, answer, kept)


def _keep_talk(user_id: str, raw: Any, note: dict) -> None:
    from services import life_store
    try:
        on = date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        on = None
    if on and on >= datetime.now(timezone.utc).date():
        life_store.save_talk_date(str(user_id), on.isoformat(), str(note.get("id")))


def _again(database: Any, user_id: str, k: Any, kept: list[dict], note: dict,
           text: str) -> list[dict]:
    """N3: once per note, the note kept under the strength it shows."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not isinstance(k, str) or not k.upper().startswith("K"):
        return []
    try:
        strength = kept[int(k[1:]) - 1]
    except (ValueError, IndexError):
        return []
    if not life_store.insert_strength_note(str(user_id), str(strength["id"]), {
            "note_id": str(note["id"]), "source": "note", "body": text,
            "noted_on": _day(note.get("created_at")) or date.today().isoformat()}):
        return []
    row = _row(f"{user_id}:strength:again:{note['id']}", "bot",
               COPY["again"].format(title=strength["title"]),
               {"strength_again": str(strength["id"])},
               stamp_after(thread_stamp(database, user_id)))
    return database.insert_lounge_messages(str(user_id), [row]) or []


def _suggest(database: Any, user_id: str, raw: Any, newest: dict, text: str,
             others: list[dict], answer: Optional[dict], kept: list[dict]) -> list[dict]:
    """N2: a trait on two different days, never one note alone, never one
    already kept."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not isinstance(raw, dict):
        return []
    title = _clip(raw.get("title"), _MAX_TITLE).strip(" .")
    sentence = _clip(raw.get("sentence"), 300)
    if not title or not sentence or any(s["title"].lower() == title.lower() for s in kept):
        return []
    picked = [i for i in raw.get("others") or [] if isinstance(i, int) and not isinstance(i, bool)]
    sources: list[dict] = []
    for i in dict.fromkeys(picked):
        if i == 0 and answer:
            sources.append({"note_id": None, "source": "goals_answer", "body": answer["body"],
                            "noted_on": answer["on"]})
        elif 1 <= i <= len(others):
            n = others[i - 1]
            sources.append({"note_id": str(n["id"]), "source": "note", "body": _text(n),
                            "noted_on": _day(n.get("created_at"))})
    day = _day(newest.get("created_at"))
    if not any(s["noted_on"] != day for s in sources):
        return []  # two different days, or nothing
    strength = life_store.insert_strength(str(user_id), {"title": title, "status": "suggested"})
    if not strength:
        return []
    for s in sources + [{"note_id": str(newest["id"]), "source": "note", "body": text,
                         "noted_on": day}]:
        life_store.insert_strength_note(str(user_id), str(strength["id"]), s)
    at = thread_stamp(database, user_id)
    meta = {"strength_id": str(strength["id"])}
    rows = [_row(f"{user_id}:strength:{strength['id']}:head", "bot", COPY["head"],
                 {**meta, "strength_step": "head"}, at),
            _row(f"{user_id}:strength:{strength['id']}:case", "bot", sentence,
                 {**meta, "strength_step": "case", "offer": OFFER}, stamp_after(at))]
    return database.insert_lounge_messages(str(user_id), rows) or []


def _owned(user_id: str, strength_id: str) -> dict:
    from services import life_store
    strength = next((s for s in life_store.list_strengths(str(user_id))
                     if str(s.get("id")) == str(strength_id)), None)
    if not strength:
        raise StrengthError("NOT_FOUND", "Not found.", 404)
    return strength


def _notes_of(user_id: str, strength_id: str) -> list[dict]:
    from services import life_store
    return [{"body": n["body"], "on": _day(n.get("noted_on")), "source": n.get("source")}
            for n in life_store.strength_notes(str(user_id))
            if str(n.get("strength_id")) == str(strength_id)]


def suggestion(database: Any, user_id: str, strength_id: str) -> dict:
    """The lens (N2): the strength Will suggests and the notes it came from,
    oldest first, each with its day (the life goals answer named as such)."""
    if not enabled(database, user_id):
        raise StrengthError("NOT_FOUND", "Not found.", 404)
    strength = _owned(user_id, strength_id)
    notes = [{**n, "label": COPY["goals_answer"] if n["source"] == "goals_answer" else None,
              "on_label": _label(n["on"])} for n in _notes_of(user_id, strength_id)]
    return {"id": str(strength["id"]), "title": strength["title"],
            "status": strength.get("status"), "notes": notes}


def answer_ask(database: Any, user_id: str, strength_id: str, choice: str) -> list[dict]:
    """Not now under "We spotted a strength!": their tap, then "Noted.", and
    the strength is not suggested again. Look opens the lens (the
    frontend's) and writes nothing."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if choice not in ("look", "not_now"):
        raise StrengthError("INVALID_CHOICE", "Unknown answer.")
    if not enabled(database, user_id):
        raise StrengthError("NOT_FOUND", "Not found.", 404)
    strength = _owned(user_id, strength_id)
    if choice == "look" or strength.get("status") != "suggested":
        return []
    life_store.update_strength(str(user_id), strength_id, {"status": "not_now"})
    at = thread_stamp(database, user_id)
    key = f"{user_id}:strength:{strength_id}:not_now"
    return database.insert_lounge_messages(str(user_id), [
        _row(key, "user", COPY["not_now"], {"strength_answer": "not_now"}, at),
        _row(key + ":noted", "bot", COPY["noted"], {}, stamp_after(at))]) or []


def decide(database: Any, user_id: str, strength_id: str, choice: str,
           text: Any = None) -> list[dict]:
    """Accept, Edit (their words) or Not now in the lens (N2): propose,
    never commit. Kept: "Noted. Added to your strengths."; Not now:
    "Noted."."""
    from services import life_store
    from services.lounge_messages import thread_stamp
    if choice not in ("accept", "edit", "not_now"):
        raise StrengthError("INVALID_CHOICE", "Unknown answer.")
    if not enabled(database, user_id):
        raise StrengthError("NOT_FOUND", "Not found.", 404)
    strength = _owned(user_id, strength_id)
    if strength.get("status") != "suggested":
        return []
    fields: dict = {"status": "not_now"}
    if choice != "not_now":
        title = strength["title"] if choice == "accept" else _clip(text, _MAX_TITLE).strip(" .")
        if not title:
            raise StrengthError("EMPTY", "No words.")
        fields = {"status": "kept", "title": title,
                  "kept_at": datetime.now(timezone.utc).isoformat()}
    if not life_store.update_strength(str(user_id), strength_id, fields):
        raise StrengthError("V2_ERROR", "Failed to keep the strength", 500)
    body = COPY["added"] if fields["status"] == "kept" else COPY["noted"]
    return database.insert_lounge_messages(str(user_id), [
        _row(f"{user_id}:strength:{strength_id}:{choice}", "bot", body,
             {"strength_decided": choice}, thread_stamp(database, user_id))]) or []


def archive(database: Any, user_id: str, strength_id: str) -> dict:
    """Only the person retires a strength (N5): archived with its date, its
    notes kept."""
    from services import life_store
    if not enabled(database, user_id):
        raise StrengthError("NOT_FOUND", "Not found.", 404)
    strength = _owned(user_id, strength_id)
    if strength.get("status") == "kept":
        life_store.update_strength(str(user_id), strength_id, {
            "status": "archived", "archived_at": datetime.now(timezone.utc).isoformat()})
    return listing(database, user_id)


def listing(database: Any, user_id: str) -> dict:
    """The Life Panel's Strengths (N1): kept, then archived, each with every
    note that shows it, newest first, and its dates."""
    from services import life_store
    if not enabled(database, user_id):
        raise StrengthError("NOT_FOUND", "Not found.", 404)
    out: dict = {"kept": [], "archived": []}
    for s in life_store.list_strengths(str(user_id)):
        if s.get("status") not in ("kept", "archived"):
            continue
        notes = list(reversed(_notes_of(user_id, str(s["id"]))))
        item = {"id": str(s["id"]), "title": s["title"],
                "kept_on": _day(s.get("kept_at")) or None,
                "archived_on": _day(s.get("archived_at")) or None,
                "notes": [{**n, "on_label": _label(n["on"]),
                           "label": COPY["goals_answer"] if n["source"] == "goals_answer" else None}
                          for n in notes]}
        out["kept" if s["status"] == "kept" else "archived"].append(item)
    return out


def today(database: Any, user_id: str, now: Optional[datetime] = None) -> list[dict]:
    """The first time the Lounge opens on the day before a talk (N4): "Your
    talk is tomorrow.", one kept strength and the note it came from. The
    talk's day from the plan's deadline or a note; no date, nothing."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not enabled(database, user_id) or _waits(database, user_id):
        return []
    tomorrow = (_today(database, user_id, now) + timedelta(days=1)).isoformat()
    talks = {t["talk_on"]: t for t in life_store.talk_dates(str(user_id))}
    deadline = str((database.get_open_plan(str(user_id)) or {}).get("deadline") or "")[:10]
    if tomorrow not in talks and deadline != tomorrow:
        return []
    if (talks.get(tomorrow) or {}).get("reminded_at"):
        return []
    kept = [s for s in life_store.list_strengths(str(user_id)) if s.get("status") == "kept"]
    if not kept:
        return []
    notes = life_store.strength_notes(str(user_id))
    # The strength with the newest note, quoting that note.
    best = max(((s, n) for s in kept for n in notes if str(n.get("strength_id")) == str(s["id"])),
               key=lambda pair: _day(pair[1].get("noted_on")), default=None)
    if not best:
        return []
    strength, note = best
    if not life_store.mark_talk_reminded(str(user_id), tomorrow):
        return []
    at = thread_stamp(database, user_id)
    key = f"{user_id}:strength:talk:{tomorrow}"
    meta = {"strength_talk": tomorrow, "strength_id": str(strength["id"])}
    rows = [_row(key + ":1", "bot", COPY["talk"], meta, at),
            _row(key + ":2", "bot", COPY["remember"].format(title=strength["title"]), meta,
                 stamp_after(at)),
            _row(key + ":3", "bot", f"“{note['body']}”",
                 {**meta, "strength_quote_on": _label(_day(note.get("noted_on")))},
                 stamp_after(stamp_after(at)))]
    return database.insert_lounge_messages(str(user_id), rows) or []
