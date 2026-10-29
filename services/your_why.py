"""Your why, every day (founder 2026-10-29, N255; words and choices signed
N258; rules: frontend docs/flows/principles.md §1 Q; prototype
https://claude.ai/artifact/1hfLf8mCif8pgC1X1Z6caJ, scenes 9 to 11).

Three lines of the person's own: their why, their vision and how they want
to treat others (Q1).

  * asked once, the next time the Lounge opens after the first life goal is
    set, with Not now | Start (the offer ``your_why``); a second Not now and
    it waits for them to ask, in any words (Q3, ``chat_turn``);
  * the sitting is the frontend's lens: three open questions, said or typed;
    Will drafts each line only from their words, quoting them (``draft``),
    and they Accept or Edit (Q2); ``save`` keeps the three;
  * every day, the first time the Lounge opens that day, the why waits as a
    grey bubble in their own words, with one question (``today``, Q4);
  * the three lines are kept in the Life Panel and Will reads them before it
    chats (``prompt_lines``, Q5); a line changes as a goal's step, dated, the
    earlier words kept (``change``, Q6).

Kept in the Life Panel's store (services/life_store.py: your_why,
your_why_versions; migration your_why_and_strengths_are_kept). Ring row
``your_why``, ring 5. Never while the person is onboarded (N243); private,
never shown to a coach (N182).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

FEATURE = "your_why"
_SURFACE = "your_why"
_NAMESPACE = uuid.UUID("9a4f2c6e-1b3d-4e7a-8c5f-0d2e6b9a1c48")
OFFER = "your_why"
#: The three lines, in order.
LINES = ("why", "vision", "treat")
#: The signed words (N258). No new words without the founder's OK.
COPY = {
    "ask": "One more thing: your why.",
    "ask_more": "Three short questions. Say or type your answers.",
    "start": "Start",
    "not_now": "Not now",
    "noted": "Noted.",
    "daily_q": "Where will it show today?",
    "set": "Noted. Your why is set.",
    "every_day": "It will be here each day, the first time you open the app.",
    "changed": "Noted. Changed on {date}.",
}
MARKS = {"why": "🔥", "vision": "🔭", "treat": "🤝"}
_MAX_ASKS = 2
_MAX_LINE = 600
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")

#: Asked by name, or a question that may be about their why (Q3).
_ASKED = re.compile(r"^\s*#\s*why\s*$", re.I)
_MAYBE = re.compile(r"\bwhy\b|purpose|vision|raison|treat (people|others)|"
                    r"po co|dlaczego|wizj|cel ", re.I)

_DRAFT_SYSTEM = """One person answered three open questions about themselves:
why they do this, what they see when it works, and how they want to treat
people. For each answered question, draft one short line in their own voice,
only from their words, and quote the words it came from, copied word for
word. A skipped question gets no line. Never invent.

Return JSON: {"why": {"line": "...", "quote": "..."} or null,
"vision": {...} or null, "treat": {...} or null}."""

_ASK_SYSTEM = """Decide whether one chat message asks to set, see or change the
person's own why (their purpose, their vision, how they want to treat people).
Questions about the app, a talk or a Take are not. Return JSON only:
{"asks": true} or {"asks": false}."""


class WhyError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def enabled(database: Any, user_id: Any) -> bool:
    """Does this person have their why? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)


def _waits(database: Any, user_id: Any) -> bool:
    """Nothing of the why while the person is onboarded (N243)."""
    from services import plan_flow
    return plan_flow.onboarding(database, user_id)


def _row(key: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": str(uuid.uuid5(_NAMESPACE, key)), "role": role,
            "kind": "text", "body": body, "metadata": meta, "client_created_at": at}


def _clip(value: Any, limit: int = _MAX_LINE) -> Optional[str]:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text[:limit] or None


def _said(quote: str, *texts: Optional[str]) -> bool:
    """The quote is found word for word in what they said."""
    def norm(t: str) -> str:
        return " ".join(re.sub(r"[^\w\s']", " ", t.lower()).split())
    q = norm(quote)
    return bool(q) and any(q in norm(t) for t in texts if t)


def _day_label(on: date) -> str:
    return f"{on.day} {_MONTHS[on.month - 1]}"


def _today(database: Any, user_id: str, now: Optional[datetime] = None) -> date:
    """Today in the person's time zone (the notebook keeps it), else UTC."""
    from services.sunday_note import _zone
    now = now or datetime.now(timezone.utc)
    zone_name = (database.get_voice_notebook_consent(str(user_id)) or {}).get("time_zone")
    return now.astimezone(_zone(zone_name)).date()


def _lines(row: dict) -> dict:
    return {line: _clip(row.get(line)) for line in LINES}


def _is_set(row: dict) -> bool:
    return any(row.get(line) for line in LINES)


def _asks_so_far(database: Any, user_id: str) -> tuple[int, Optional[str], bool]:
    """(times asked, the last answer, the ask still open) from the thread."""
    rows = database.get_lounge_messages_page(str(user_id), limit=300) or []
    asked, answer, open_ = 0, None, False
    for row in reversed(rows):
        meta = row.get("metadata") or {}
        if meta.get("your_why_ask"):
            asked, open_ = max(asked, int(meta["your_why_ask"])), meta.get("offer") == OFFER or open_
        if meta.get("your_why_answer"):
            answer, open_ = meta["your_why_answer"], False
    return asked, answer, open_


def today(database: Any, user_id: str, now: Optional[datetime] = None) -> list[dict]:
    """The first time the Lounge opens: the ask, once after the first goal is
    set and once more after a Not now (Q3); else, once a day, the why in
    their own words and "Where will it show today?" (Q4). [] otherwise."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not enabled(database, user_id) or _waits(database, user_id):
        return []
    row = life_store.get_why(str(user_id))
    at = thread_stamp(database, user_id)
    if not _is_set(row):
        if not life_store.list_goals(str(user_id)):
            return []
        asked, answer, open_ = _asks_so_far(database, user_id)
        if asked >= _MAX_ASKS or answer == "start" or open_ or (asked and answer != "not_now"):
            return []
        n = asked + 1
        rows = [_row(f"{user_id}:why:ask:{n}:1", "bot", COPY["ask"], {"your_why_ask": n}, at),
                _row(f"{user_id}:why:ask:{n}:2", "bot", COPY["ask_more"],
                     {"offer": OFFER, "your_why_ask": n}, stamp_after(at))]
        return database.insert_lounge_messages(str(user_id), rows) or []
    why = _clip(row.get("why"))
    if not why:
        return []
    day = _today(database, user_id, now).isoformat()
    meta = {"your_why_day": day}
    rows = [_row(f"{user_id}:why:day:{day}:1", "bot", f"{MARKS['why']} {why}",
                 {**meta, "your_why_line": "why"}, at),
            _row(f"{user_id}:why:day:{day}:2", "bot", COPY["daily_q"], meta, stamp_after(at))]
    # One a day: the rows' names are the day's, so a second open writes nothing new.
    seen = {r.get("client_id") for r in database.get_lounge_messages_page(str(user_id), limit=50) or []}
    if rows[0]["client_id"] in seen:
        return []
    return database.insert_lounge_messages(str(user_id), rows) or []


def answer_ask(database: Any, user_id: str, choice: str) -> list[dict]:
    """Start or Not now under the ask: the tap in the thread, and "Noted."
    after Not now. Start opens the lens (the frontend's)."""
    from services.lounge_messages import stamp_after, thread_stamp
    if choice not in ("start", "not_now"):
        raise WhyError("INVALID_CHOICE", "Unknown answer.")
    if not enabled(database, user_id):
        raise WhyError("NOT_FOUND", "Not found.", 404)
    asked, _answer, _open = _asks_so_far(database, user_id)
    at = thread_stamp(database, user_id)
    key = f"{user_id}:why:{choice}:{max(1, asked)}"
    rows = [_row(key, "user", COPY[choice], {"your_why_answer": choice}, at)]
    if choice == "not_now":
        rows.append(_row(key + ":noted", "bot", COPY["noted"], {}, stamp_after(at)))
    return database.insert_lounge_messages(str(user_id), rows) or []


def chat_turn(database: Any, user_id: str, question: str) -> Optional[dict]:
    """"#why", or an ask for their why in their own words: answered and
    opening the lens (``your_why_open``, not an offer: it opens because they
    asked). None for anything else and anyone without it."""
    text = (question or "").strip()
    named = bool(_ASKED.match(text))
    if not text or (not named and (text.startswith("#") or not _MAYBE.search(text))):
        return None
    if not enabled(database, user_id) or _waits(database, user_id):
        return None
    if not named:
        try:
            if _model(_ASK_SYSTEM, text, user_id, "SPEC_YOUR_WHY_ASK").get("asks") is not True:
                return None
        except Exception as error:  # noqa: BLE001 -- the chat answers as before
            logger.warning("your why: ask not read user=%s: %s", user_id, error)
            return None
    return {"answer": COPY["ask_more"], "row_metadata": {"your_why_open": True}}


def _model(system: str, user: str, user_id: str, spec_name: str) -> dict:
    from services import llm_config
    from services.llm import chat_complete
    result = chat_complete(spec=getattr(llm_config, spec_name), system=system, user=user,
                           surface=_SURFACE, user_id=str(user_id))
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else {}


def draft(database: Any, user_id: str, answers: Any) -> dict:
    """Will's drafts (Q2): ``{line: {"line", "quote"} or None}``, each only
    from their words, the quote found word for word in their answer. A
    skipped question gets none; all three skipped, nothing is drafted."""
    from services import life_store
    if not enabled(database, user_id):
        raise WhyError("NOT_FOUND", "Not found.", 404)
    answers = answers if isinstance(answers, dict) else {}
    said = {line: _clip(answers.get(line), 2000) for line in LINES}
    life_store.save_why(str(user_id), {"draft": {"answers": said}})
    if not any(said.values()):
        return {line: None for line in LINES}
    labels = {"why": "Why do you do this?", "vision": "What do you see when it works?",
              "treat": "How do you want to treat people?"}
    user = "\n".join(f"{labels[line]} {said[line] or '(skipped)'}" for line in LINES)
    parsed = _model(_DRAFT_SYSTEM, user, user_id, "SPEC_YOUR_WHY_DRAFT")
    out: dict = {}
    for line in LINES:
        raw = parsed.get(line)
        item: dict = raw if isinstance(raw, dict) else {}
        words, quote = _clip(item.get("line")), _clip(item.get("quote"))
        if not said[line] or not words:
            out[line] = None
            continue
        out[line] = {"line": words, "quote": quote if quote and _said(quote, said[line]) else said[line]}
    return out


def save(database: Any, user_id: str, lines: Any) -> list[dict]:
    """The lines they accepted or edited (Q2): kept, and in the Lounge
    "Noted. Your why is set." and "It will be here each day, …"."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not enabled(database, user_id):
        raise WhyError("NOT_FOUND", "Not found.", 404)
    lines = lines if isinstance(lines, dict) else {}
    kept = {line: _clip(lines.get(line)) for line in LINES}
    if not any(kept.values()):
        raise WhyError("EMPTY", "No words.")
    if not life_store.save_why(str(user_id), {**kept, "draft": {},
                                              "set_at": datetime.now(timezone.utc).isoformat()}):
        raise WhyError("V2_ERROR", "Failed to keep your why", 500)
    at = thread_stamp(database, user_id)
    rows = [_row(f"{user_id}:why:set:1", "bot", COPY["set"], {"your_why_set": True}, at),
            _row(f"{user_id}:why:set:2", "bot", COPY["every_day"], {"your_why_set": True},
                 stamp_after(at))]
    return database.insert_lounge_messages(str(user_id), rows) or []


def change(database: Any, user_id: str, line: str, text: Any) -> dict:
    """A changed line (Q6): the earlier words kept as a dated version, then
    "Noted. Changed on {date}." in the thread. Returns the state."""
    from services import life_store
    from services.lounge_messages import thread_stamp
    if line not in LINES:
        raise WhyError("INVALID_LINE", "Unknown line.")
    if not enabled(database, user_id):
        raise WhyError("NOT_FOUND", "Not found.", 404)
    words = _clip(text)
    if not words:
        raise WhyError("EMPTY", "No words.")
    row = life_store.get_why(str(user_id))
    before = _clip(row.get(line))
    if words == before:
        return state(database, user_id)
    if not life_store.save_why(str(user_id), {line: words}):
        raise WhyError("V2_ERROR", "Failed to keep the change", 500)
    life_store.insert_why_version(str(user_id), line=line, before=before, after=words)
    on = _today(database, user_id)
    key = f"{user_id}:why:changed:{line}:{uuid.uuid4()}"
    database.insert_lounge_messages(str(user_id), [
        _row(key, "bot", COPY["changed"].format(date=_day_label(on)),
             {"your_why_changed": line}, thread_stamp(database, user_id))])
    return state(database, user_id)


def state(database: Any, user_id: str) -> dict:
    """The three lines, when they were set, each line's newest change (its
    date and the words before) and every version newest first."""
    from services import life_store
    if not enabled(database, user_id):
        raise WhyError("NOT_FOUND", "Not found.", 404)
    row = life_store.get_why(str(user_id))
    changes: dict = {}
    history: list[dict] = []
    for v in life_store.why_versions(str(user_id)):
        on = str(v.get("created_at") or "")[:10]
        changes[v["line"]] = {"on": on, "earlier": v.get("before_text")}
        history.append({"on": on, "line": v["line"], "before": v.get("before_text"),
                        "after": v.get("after_text")})
    return {"lines": _lines(row), "set_on": str(row.get("set_at") or "")[:10] or None,
            "changes": changes, "history": list(reversed(history)),
            "draft": (row.get("draft") or {}).get("answers") or {}}


def prompt_lines(database: Any, user_id: Any) -> str:
    """The three lines, for Will's chat prompt (Q5); "" when there are none
    or the person has no why. Facts, not instructions."""
    from services import life_store
    try:
        if not enabled(database, user_id):
            return ""
        lines = _lines(life_store.get_why(str(user_id)))
    except Exception as error:  # noqa: BLE001 -- the chat answers either way
        logger.warning("your why: not read for the prompt user=%s: %s", user_id, error)
        return ""
    labels = {"why": "Their why", "vision": "Their vision", "treat": "How they want to treat people"}
    got = [f"  • {labels[line]}: {lines[line]}" for line in LINES if lines[line]]
    return ("In their own words:\n" + "\n".join(got) + "\n") if got else ""
