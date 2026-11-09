"""Asked when they join (N487; its words signed in N491, N496 and N502).

A person who shares what they know sets a few practical questions; everyone
who joins through their link is asked them, one at a time, in their chat with
that person, as that person's own messages, sent for them (N487 item 4). The
joiner answers only by tapping (N483 item 3): one answer, or several where a
question takes more than one, then Send. The person who shares never watches
their own questions wait: they see one card, "{name}'s answers", once the
joiner is done (N487 item 7).

  * ``mine`` / ``save``: the questions a person has set, kept on their
    profile row (``people_profiles.join_questions``,
    migrations/a_person_keeps_their_join_questions.sql). NULL,
    or a database without the column yet, means no questions. ``kept``
    tells Will's setup (``services/join_setup.py``) whether a set can be
    kept at all, and whether one was, an empty one included.
  * ``suggest`` / ``practical`` / ``ready``: what Will does with a question
    someone types in the setup (N487 item 2): give it answers to tap, or
    leave it out, with a word why. Rules, no provider call.
  * ``begin``: when a chat is made through a link, its first question (and
    any sentence before it), as the link owner's messages.
  * ``answer``: the joiner's tap; then the next question, or the closing
    line and the card.
  * ``hidden``: which of these messages a member does not see.

What a message carries, in ``chat_messages.meta``:
  * a question or a sentence, written by the owner's member:
    ``{"setup": {"i", "kind", "answers", "multi"}}``; the first one also
    keeps the whole set as it stood (``"all"``, ``"plan"``), so a change the
    owner makes later reaches only people who join later;
  * an answer, written by the joiner's member:
    ``{"setup_answer": {"to", "i", "picked", "deadline"?}}``;
  * the card, written by the joiner's member, shown only to the owner:
    ``{"setup_card": {"rows": [{"k", "v"}]}}``.

No provider call, no recording: nothing here passes the processing-
authorization path. Nothing is pushed: the joiner is in the chat when it
begins, and the owner learns from the card's row in their list.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROFILES = "people_profiles"
COLUMN = "join_questions"
MESSAGES, MEMBERS = "chat_messages", "chat_members"

MAX_LINES = 8
MAX_WORDS = 160
MAX_ANSWERS = 6
MAX_ANSWER = 40

# ── The words (signed: N491, N496, N502) ────────────────────────────────
PLAN_LINE = "Let's build our knowledge base {span}."
HURRY = "Are you in a hurry?"
LANGUAGES = "Which languages can we use?"
CLOSING = "Thanks, that's everything. When you're ready, tap + and ask me your first question."
NO, YES = "No", "Yes"
TIMES = ["Mornings", "Afternoons", "Evenings"]
CARD_DEADLINE, CARD_LANGUAGES = "Deadline", "Languages"
#: How far ahead a person plans (N491 item 2): the words of the plan line,
#: and one step of the plan, the first deadline when the joiner is in no hurry.
SPANS = {"week": ("a week at a time", 7), "month": ("a month at a time", 30),
         "quarter": ("a quarter at a time", 91)}

KINDS = ("say", "hurry", "date", "languages", "tap")


from services.chats import ChatsError  # noqa: E402  (services.chats imports this module lazily)


class JoinQuestionsError(ChatsError):
    """Answered by the chats' routes as their own errors."""


# ── What Will does with a typed question (N487 item 2) ──────────────────

_PRACTICAL = re.compile(
    r"hurry|deadline|\bdate\b|\bwhen\b|plan|language|week|month|quarter|\bcall|\bmeet|"
    r"time zone|\bcity\b|country|\bwhere\b|available|how often|ready", re.I)
_YES_NO = re.compile(r"^(do|does|are|is|can|could|will|would|should|have|has)\b", re.I)


def practical(question: str) -> bool:
    """About time, the plan, the language or calls: kept. Anything about the
    work itself is heard in the recordings, so it is left out (N487 item 2)."""
    q = question.strip()
    return not q.endswith("?") or bool(_PRACTICAL.search(q))


def suggest(question: str, languages: list[str]) -> list[str]:
    """The answers Will gives a question typed without any; none when he
    cannot tell (then it is left out)."""
    q = question.strip()
    if re.search(r"hurry", q, re.I):
        return [NO, YES]
    if re.search(r"language", q, re.I):
        return list(languages)
    if re.search(r"\b(call|meet)", q, re.I) and re.search(r"\b(when|what time)\b", q, re.I):
        return list(TIMES)
    if _YES_NO.search(q):
        return [NO, YES]
    return []


def _kind(question: str) -> str:
    q = question.strip()
    if not q.endswith("?"):
        return "say"
    if re.search(r"hurry", q, re.I):
        return "hurry"
    if re.search(r"language", q, re.I):
        return "languages"
    return "tap"


def ready(said: list[str], languages: list[str]) -> dict:
    """Lines as someone typed them, made ready for joiners: {"keep": lines,
    "about": questions about the work, "open": questions with no answers to
    tap, "added": whether Will gave any its answers}. A line may carry its
    own answers after it, split by "/" (what "Change it" writes)."""
    keep, about, open_, added = [], [], [], False
    for raw in said[:MAX_LINES]:
        text = str(raw or "").strip()[:MAX_WORDS]
        if not text:
            continue
        q, _, rest = text.rpartition("?")
        if not _:
            keep.append(_line(text, [], False))
            continue
        q = (q + "?").strip()
        if not practical(q):
            about.append(q)
            continue
        given = [a.strip()[:MAX_ANSWER] for a in rest.split("/") if a.strip()][:MAX_ANSWERS]
        answers = given or suggest(q, languages)
        if not answers:
            open_.append(q)
            continue
        added = added or not given
        keep.append(_line(q, answers, _kind(q) == "languages"))
    return {"keep": keep, "about": about, "open": open_, "added": added}


def _line(q: str, answers: list[str], multi: bool) -> dict:
    return {"q": q, "answers": answers, "multi": multi, "kind": _kind(q)}


# ── Kept on the profile ─────────────────────────────────────────────────

def _table(database: Any, name: str) -> Any:
    return database.client.table(name)


def _rows(query: Any) -> list[dict]:
    try:
        return list(query.execute().data or [])
    except Exception:
        # A database without the join_questions column
        # (migrations/a_person_keeps_their_join_questions.sql) reads as none.
        logger.warning("join_questions: a read failed", exc_info=True)
        return []


def normalize(payload: Any) -> Optional[dict]:
    """What may be kept: a plan ("week", "month", "quarter" or none) and up to
    eight lines, each a sentence or a question with two to six answers. None
    for an empty set (no questions)."""
    body = payload if isinstance(payload, dict) else {}
    plan = body.get("plan") if body.get("plan") in SPANS else None
    lines: list[dict] = []
    if plan:
        lines += [_line(PLAN_LINE.format(span=SPANS[plan][0]), [], False),
                  _line(HURRY, [NO, YES], False)]
    for raw in (body.get("lines") or [])[:MAX_LINES]:
        if not isinstance(raw, dict):
            continue
        q = str(raw.get("q") or "").strip()[:MAX_WORDS]
        if not q or q == HURRY or q.startswith("Let's build our knowledge base"):
            continue
        answers = [str(a).strip()[:MAX_ANSWER] for a in (raw.get("answers") or []) if str(a).strip()]
        if q.endswith("?") and not 2 <= len(answers) <= MAX_ANSWERS:
            raise JoinQuestionsError("NO_ANSWERS", "Every question needs two to six answers.")
        lines.append(_line(q, answers if q.endswith("?") else [],
                           bool(raw.get("multi")) and q.endswith("?")))
    if not lines:
        return None
    return {"v": 1, "plan": plan, "lines": lines[:MAX_LINES + 2]}


def mine(database: Any, user_id: str) -> Optional[dict]:
    """The questions a person has set, or None. A database without the
    column yet (before a_person_keeps_their_join_questions.sql) reads as none."""
    rows = _rows(_table(database, PROFILES).select(f"user_id,{COLUMN}")
                 .eq("user_id", str(user_id)).limit(1))
    value = rows[0].get(COLUMN) if rows else None
    return value if isinstance(value, dict) and value.get("lines") else None


def save(database: Any, user_id: str, payload: Any) -> dict:
    """Keep a person's questions, replacing what was there; {"questions"}.
    An empty set is kept as a set with no lines (``mine`` reads it as none),
    so Will's setup knows it was answered (``services/join_setup.py``)."""
    from datetime import datetime, timezone
    value = normalize(payload)
    stamp = datetime.now(timezone.utc).isoformat()
    stored = {**(value or {"v": 1, "plan": None, "lines": []}), "updated_at": stamp}
    table = _table(database, PROFILES)
    try:
        if _rows(table.select("user_id").eq("user_id", str(user_id)).limit(1)):
            table.update({COLUMN: stored, "updated_at": stamp}).eq("user_id", str(user_id)).execute()
        else:
            table.insert({"user_id": str(user_id), COLUMN: stored}).execute()
    except Exception as e:
        logger.error("join_questions: not kept for %s", user_id, exc_info=True)
        raise JoinQuestionsError("NOT_SAVED", "Could not keep them.", 503) from e
    return {"questions": stored if value else None}


def kept(database: Any, user_id: str) -> tuple[bool, Optional[dict]]:
    """(whether questions can be kept at all, the set as kept or None).
    False before a_person_keeps_their_join_questions.sql: no column to read."""
    try:
        rows = (_table(database, PROFILES).select(f"user_id,{COLUMN}")
                .eq("user_id", str(user_id)).limit(1).execute().data or [])
    except Exception:
        logger.warning("join_questions: the column could not be read", exc_info=True)
        return False, None
    value = rows[0].get(COLUMN) if rows else None
    return True, value if isinstance(value, dict) else None


# ── In the joiner's chat ────────────────────────────────────────────────

def hidden(row: dict, me: str) -> bool:
    """A member does not see: their own questions, sent for them, nor the
    joiner's taps (the owner, N487 item 7); the card (the joiner)."""
    meta = row.get("meta") or {}
    mine_ = str(row.get("author_member_id")) == str(me)
    if "setup" in meta:
        return mine_
    if "setup_answer" in meta:
        return not mine_
    if "setup_card" in meta:
        return mine_
    return False


def _members(database: Any, thread: str) -> list[dict]:
    return _rows(_table(database, MEMBERS).select("id,user_id,display_name").eq("thread_id", thread))


def _insert(database: Any, thread: str, member: str, body: str, meta: dict) -> Optional[dict]:
    rows = _rows(_table(database, MESSAGES).insert({
        "thread_id": thread, "author_member_id": member, "kind": "text",
        "body": body, "meta": meta}))
    return rows[0] if rows else None


def _deadline_known(database: Any, user_id: Optional[str]) -> Optional[date]:
    """A day the joiner already picked for their plan (N254: one project, one
    deadline), or None; always None for a widget's visitor, who has no plan
    (N567)."""
    from services.plan_flow import _parse_day
    if not user_id:
        return None
    try:
        plan = database.get_open_plan(str(user_id)) or {}
    except Exception:
        logger.warning("join_questions: the plan could not be read", exc_info=True)
        return None
    day = _parse_day(plan.get("deadline"))
    return day if day and not plan.get("deadline_given") else None


def _set_deadline(database: Any, user_id: str, day: date) -> None:
    """The joiner's plan takes the day, unless they picked one already.
    Best-effort: the answer is kept in the chat either way."""
    try:
        plan = database.get_open_plan(str(user_id))
        if plan and not _deadline_known(database, user_id):
            database.update_plan(str(user_id), plan["id"],
                                 {"deadline": day.isoformat(), "deadline_given": False})
    except Exception:  # noqa: BLE001
        logger.warning("join_questions: the plan kept no deadline", exc_info=True)


def begin(database: Any, thread: str, owner_id: str, joiner_id: str) -> None:
    """A chat just made through a link: the owner's first lines, up to the
    first question. Best-effort: joining never fails on it."""
    try:
        questions = mine(database, owner_id)
        if not questions:
            return
        members = {str(m.get("user_id")): str(m["id"]) for m in _members(database, thread)}
        if owner_id not in members or joiner_id not in members:
            return
        _advance(database, thread, members[owner_id], members[joiner_id], joiner_id,
                 questions, 0, first=True)
    except Exception:  # noqa: BLE001
        logger.warning("join_questions: the questions did not begin in %s", thread, exc_info=True)


def begin_for_visitor(database: Any, thread: str, owner_id: str, owner_member: str,
                      visitor_member: str) -> list[dict]:
    """A widget's chat just opened (N567 item 4): the owner's first lines to
    the visitor, up to the first question, as ``begin`` does for someone who
    joins; the rows posted. Best-effort: the widget opens either way."""
    try:
        questions = mine(database, owner_id)
        if not questions:
            return []
        return _advance(database, thread, owner_member, visitor_member, None, questions, 0,
                        first=True, closing=False)
    except Exception:  # noqa: BLE001
        logger.warning("join_questions: the questions did not begin in %s", thread, exc_info=True)
        return []


def _advance(database: Any, thread: str, owner: str, joiner: str, joiner_id: Optional[str],
             questions: dict, start: int, *, first: bool = False, closing: bool = True) -> list[dict]:
    """Post lines from ``start``: sentences, then the next question; at the
    end, the closing line (not in a widget, whose visitor cannot tap "+",
    N567) and the card. Returns the rows posted."""
    lines = questions["lines"]
    posted: list[dict] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line["kind"] == "hurry" and _deadline_known(database, joiner_id):
            i += 1
            continue
        meta = {"setup": {"i": i, "kind": line["kind"], "answers": line["answers"],
                          "multi": bool(line.get("multi"))}}
        if first:
            meta["setup"]["all"] = lines
            meta["setup"]["plan"] = questions.get("plan")
            first = False
        row = _insert(database, thread, owner, line["q"], meta)
        if row:
            posted.append(row)
        if line["kind"] != "say":
            return posted
        i += 1
    if start > 0 and closing:
        row = _insert(database, thread, owner, CLOSING, {"setup": {"i": len(lines), "kind": "say",
                                                                    "answers": [], "multi": False}})
        if row:
            posted.append(row)
    if start > 0:
        card = _card(database, thread, questions)
        if card:
            _insert(database, thread, joiner, "", {"setup_card": {"rows": card}})
    return posted


def _setup_rows(database: Any, thread: str) -> list[dict]:
    return [r for r in _rows(_table(database, MESSAGES).select("id,author_member_id,body,meta,created_at")
                             .eq("thread_id", thread).order("created_at"))
            if any(k in (r.get("meta") or {}) for k in ("setup", "setup_answer", "setup_card"))]


def _snapshot(rows: list[dict]) -> Optional[dict]:
    for r in rows:
        setup = (r.get("meta") or {}).get("setup") or {}
        if isinstance(setup.get("all"), list):
            return {"lines": setup["all"], "plan": setup.get("plan")}
    return None


def _card(database: Any, thread: str, questions: dict) -> list[dict]:
    """"{name}'s answers": one row per answered question; the deadline and
    the languages by name, any other question by its words."""
    out = []
    for r in _setup_rows(database, thread):
        a = (r.get("meta") or {}).get("setup_answer")
        if not isinstance(a, dict):
            continue
        i = a.get("i")
        line = questions["lines"][i] if isinstance(i, int) and 0 <= i < len(questions["lines"]) else {}
        if a.get("deadline"):
            out.append({"k": CARD_DEADLINE, "v": _day_text(date.fromisoformat(a["deadline"]))})
        elif line.get("kind") == "languages":
            out.append({"k": CARD_LANGUAGES, "v": ", ".join(a.get("picked") or [])})
        else:
            out.append({"k": str(line.get("q") or "").rstrip("?"), "v": ", ".join(a.get("picked") or [])})
    return out


def _day_text(day: date) -> str:
    from services import plan as P
    return P.fmt_day(day)


def _question(rows: list[dict], message_id: Any, me: str) -> tuple[dict, dict]:
    """The other member's question the tap is for, not yet answered."""
    asked = next((r for r in rows if str(r["id"]) == str(message_id)), None)
    setup = ((asked or {}).get("meta") or {}).get("setup")
    if not asked or not isinstance(setup, dict) or setup.get("kind") == "say" \
            or str(asked["author_member_id"]) == me:
        raise JoinQuestionsError("NOT_FOUND", "No such question.", 404)
    if any(((r.get("meta") or {}).get("setup_answer") or {}).get("to") == str(asked["id"]) for r in rows):
        raise JoinQuestionsError("ANSWERED", "Already answered.", 409)
    return asked, setup


def _picked(setup: dict, body: dict) -> list[str]:
    """The tapped answers, in the question's order: one, or several where
    the question takes more than one."""
    answers = setup.get("answers") or []
    picked = sorted({p for p in (body.get("picked") or []) if p in answers}, key=answers.index)
    if not picked or (len(picked) > 1 and not setup.get("multi")):
        raise JoinQuestionsError("PICK_ONE", "Tap one of the answers.")
    return picked


def _hurry_day(picked: list[str], body: dict, plan: Optional[str]) -> date:
    """"Yes" comes with the day from the date picker, after today; "No" puts
    the deadline one step of the plan away (N487 item 4)."""
    today = date.today()
    if picked != [YES]:
        return today + timedelta(days=SPANS.get(plan or "month", SPANS["month"])[1])
    try:
        day = date.fromisoformat(str(body.get("date") or ""))
    except ValueError:
        raise JoinQuestionsError("INVALID_DATE", "Pick a day after today.") from None
    if day <= today:
        raise JoinQuestionsError("INVALID_DATE", "Pick a day after today.")
    return day


def answer(database: Any, user_id: Any, thread_id: Any, message_id: Any, payload: Any) -> dict:
    """POST /v2/chats/<id>/setup/<message_id> {"picked": [...], "date"?}: the
    joiner's tap on one of the owner's questions. {"messages": [what the
    joiner now sees: their answer, then what follows]}."""
    from services import chats
    me = chats.member(database, user_id, thread_id)
    return answer_as(database, me, str(user_id), message_id, payload)


def answer_as(database: Any, me: dict, user_id: Optional[str], message_id: Any, payload: Any) -> dict:
    """``answer`` for a seat in the chat: a member's (``user_id``, whose plan
    takes the deadline) or a widget visitor's (no ``user_id``, no plan, no
    closing line, N567)."""
    from services import chats
    thread, my_member = str(me["thread_id"]), str(me["id"])
    rows = _setup_rows(database, thread)
    asked, setup = _question(rows, message_id, my_member)
    body = payload if isinstance(payload, dict) else {}
    picked = _picked(setup, body)
    questions = _snapshot(rows)
    if not questions:
        raise JoinQuestionsError("NOT_FOUND", "No such question.", 404)
    record: dict = {"to": str(asked["id"]), "i": setup["i"], "picked": picked}
    shown_body = ", ".join(picked)
    if setup["kind"] == "hurry":
        day = _hurry_day(picked, body, questions.get("plan"))
        record["deadline"] = day.isoformat()
        if picked == [YES]:
            shown_body = _day_text(day)
        if user_id:
            _set_deadline(database, user_id, day)
    mine_row = _insert(database, thread, my_member, shown_body, {"setup_answer": record})
    if not mine_row:
        raise JoinQuestionsError("NOT_SAVED", "Could not send it.", 503)
    owner = str(asked["author_member_id"])
    after = _advance(database, thread, owner, my_member, user_id, questions, int(setup["i"]) + 1,
                     closing=bool(user_id))
    authors = chats._authors(database, thread)
    return {"messages": [chats._shown(r, my_member, authors) for r in [mine_row, *after]]}


def asks(database: Any, thread: str) -> bool:
    """Whether the chat began with its owner's questions: the joiner's line
    at the top then says a few questions come first (N496 item 1)."""
    return bool(_snapshot(_setup_rows(database, thread)))
