"""Will's setup for a person who shares (N487 items 2 and 3, N503; its words
signed in N491 and N502, as the prototype "Asked When They Join" shows them).

The first time a person opens "Add someone to chat with" (N503 item 1), Will
asks in his chat, one question at a time, what everyone who joins through
their link will be asked (``services/join_questions.py``): how far ahead
they plan, which languages to use (only for someone who speaks two), and
anything else practical. Then the summary, as someone new will see it, with
"Change it" and "That's right". Nothing is kept until "That's right"; "Your
questions for people who join ›" opens the summary again later (N503 item 2).

  * ``begin``: the setup's first lines, or its open question again at the
    bottom; {"started": False} once the questions are set, or before
    migration 0511, when nothing could be kept.
  * ``answer``: a tap, or the words typed after "Something else" or under
    "What should change?"; then Will's next lines.
  * ``again``: the summary again, from "Your questions for people who join ›".

Rows of the one Lounge thread (``lounge_messages``, kind "text"), each with
``metadata.join_setup``:
  * Will's sentence: {"step": "say"};
  * Will's question that waits: {"step": "plan" | "languages" | "more" |
    "peek" | "change", "chips": [...], "draft": {...}}. The draft is the set
    as it stands, carried from question to question. The summary is the
    question "peek"; it also carries "lines", the questions as someone new
    will see them;
  * the end: {"step": "set"} ("You're set.", with "Copy my link ›" and "Your
    questions for people who join ›") or {"step": "saved"};
  * the person's tap or words, role "user": {"step": "answer", "to": the
    question's client id}.

No provider call and no recording: Will reads typed words by rules
(``join_questions.ready`` and ``change`` here), so nothing passes the
processing-authorization path.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from typing import Any, Optional

from services import join_questions as J
from services.join_questions import JoinQuestionsError

logger = logging.getLogger(__name__)

_NS = uuid.UUID("0b7c4d1e-5a2f-4e86-9d3b-6f1a8c2e7b45")
MAX_SAID = 400

# ── The words (signed: N491, N502) ──────────────────────────────────────
INTRO = ("Everyone who joins through your link builds a knowledge base with you. "
         "I'll ask them a few questions first.")
PLAN_Q = "How far ahead do you like to plan?"
#: The plan's answers, the likely one first (N371 item 2).
PLANS = {"A month at a time": "month", "A week at a time": "week",
         "A quarter at a time": "quarter", "No deadline": None}
LANGUAGES_Q = "Should I ask which languages to use: {languages} or both?"
MORE_Q = "Anything else practical you'd like to ask?"
THATS_ALL = "That's all"
ADDED = "They answer by tapping, so I've given it answers. Change them if you like."
ABOUT = "I've left out {questions}: you'll hear that in their recording."
OPEN = ("I left out {questions} because I couldn't think of answers they could tap. "
        "To keep {it}, tap “Change it” and tell me the answers.")
PEEK = "This is what someone new will see when they open your chat:"
CHANGE_IT, THATS_RIGHT = "Change it", "That's right"
CHANGE_Q = "What should change?"
DONE = "Done."
NEW_VERSION = "Here's the new version:"
UNCLEAR = ("I couldn't tell what to change, so it's as it was. "
           "Tap “Change it” and put it another way.")
SET = ("You're set. Each question that comes to your chats, and each answer you give, "
       "builds a knowledge base you share.")
AGAIN = "Here are your questions for people who join:"
SAVED = "Saved. Everyone who joins from now on will see these."

WAITS = ("plan", "languages", "more", "peek", "change")


# ── What the person speaks ──────────────────────────────────────────────

def _languages(database: Any, user_id: str) -> list[str]:
    """The two languages the person speaks most, by name: the ones they
    rate in, then their Takes' (N487 item 2: the profile holds none yet).
    Two at most, since the question offers "or both"."""
    from services.rater_languages import language_name
    said: Counter = Counter()
    try:
        for code in database.get_user_proficient_languages(str(user_id)) or []:
            said[code] += 1000
        rows = (database.client.table("recordings").select("transcription_language")
                .eq("user_id", str(user_id)).limit(200).execute().data or [])
        said.update(r.get("transcription_language") for r in rows if r.get("transcription_language"))
    except Exception:
        logger.warning("join_setup: the languages could not be read", exc_info=True)
    names = [language_name(code) for code, _ in said.most_common()]
    return list(dict.fromkeys(n for n in names if n))[:2]


# ── Rows ────────────────────────────────────────────────────────────────

def _say(body: str) -> tuple:
    return (str(uuid.uuid4()), "bot", body, {"step": "say"})


def _ask(step: str, body: str, chips: list[str], draft: dict, **more: Any) -> tuple:
    return (str(uuid.uuid4()), "bot", body, {"step": step, "chips": chips, "draft": draft, **more})


def _answer_id(question: str) -> str:
    return str(uuid.uuid5(_NS, f"{question}:answer"))


def _write(database: Any, user_id: str, items: list[tuple]) -> list[dict]:
    """Rows at the bottom of Will's chat, in order."""
    from services.lounge_messages import stamp_after, thread_stamp
    at = thread_stamp(database, user_id)
    rows = [{"client_id": cid, "role": role, "kind": "text", "body": body,
             "metadata": {"join_setup": meta},
             "client_created_at": stamp_after(at, gap_ms=i) if i else at}
            for i, (cid, role, body, meta) in enumerate(items)]
    return database.insert_lounge_messages(str(user_id), rows) or []


def _setup_of(row: Optional[dict]) -> dict:
    meta = (row or {}).get("metadata") or {}
    setup = meta.get("join_setup") if isinstance(meta, dict) else None
    return setup if isinstance(setup, dict) else {}


# ── The draft ───────────────────────────────────────────────────────────

def _fresh(languages: list[str], later: bool = False) -> dict:
    return {"plan": None, "lines": [], "languages": languages, "later": later, "notes": []}


def _shown(draft: dict) -> list[dict]:
    """The questions as someone new will see them, the plan's two first."""
    try:
        value = J.normalize({"plan": draft.get("plan"), "lines": draft.get("lines") or []})
    except JoinQuestionsError:
        return []
    return list((value or {}).get("lines") or [])


def _own_lines(value: Optional[dict]) -> list[dict]:
    """A kept set's own lines, without the two the plan writes."""
    return [line for line in (value or {}).get("lines") or []
            if line.get("q") != J.HURRY and not str(line.get("q") or "").startswith("Let's build our knowledge base")]


def _quote(questions: list[str]) -> str:
    return " and ".join(f"“{q}”" for q in questions)


def _own(draft: dict, said: str) -> None:
    """The person's own words: a question made ready for joiners, or left
    out with a word why (N487 item 2)."""
    out = J.ready([said], draft.get("languages") or [])
    draft["lines"] = (draft.get("lines") or []) + out["keep"]
    notes = draft.setdefault("notes", [])
    if out["about"]:
        notes.append(ABOUT.format(questions=_quote(out["about"])))
    if out["open"]:
        notes.append(OPEN.format(questions=_quote(out["open"]), it="them" if len(out["open"]) > 1 else "it"))
    if out["added"]:
        notes.append(ADDED)


_DROP = re.compile(r"\b(drop|remove|delete|take out|no)\b", re.I)
_OR = re.compile(r"([a-z]+(?:\s[a-z]+)?)\s+or\s+([a-z]+(?:\s[a-z]+)?)", re.I)
#: What a change names, and the line it means; None is the plan's two lines.
_TOPICS = ((re.compile(r"language", re.I), re.compile(r"language", re.I)),
           (re.compile(r"\bcall", re.I), re.compile(r"\bcall", re.I)),
           (re.compile(r"hurry|deadline|date", re.I), None))


def _drop(part: str, draft: dict) -> bool:
    done = False
    for named, line_re in _TOPICS:
        if not named.search(part):
            continue
        if line_re is None:
            done = done or bool(draft.get("plan"))
            draft["plan"] = None
            continue
        lines = draft.get("lines") or []
        draft["lines"] = [line for line in lines if not line_re.search(line.get("q") or "")]
        done = done or len(draft["lines"]) != len(lines)
    return done


def _answers(part: str, match: re.Match, draft: dict) -> bool:
    line_re = next((line for named, line in _TOPICS if line and named.search(part)), None)
    first = re.sub(r"^(offer|give|make it|make them)\s+", "", match[1], flags=re.I)
    second = re.sub(r"\s+for\b.*$", "", match[2], flags=re.I)
    target = next((line for line in draft.get("lines") or []
                   if line_re and line_re.search(line.get("q") or "") and line.get("answers") != [J.NO, J.YES]), None)
    if not target:
        return False
    target["answers"] = [w[:1].upper() + w[1:] for w in (first, second)]
    return True


def change(said: str, draft: dict) -> bool:
    """Will makes the change from the person's own words (N487 item 3), by
    rules: drop a question, give one new answers ("weekdays or weekends for
    calls"), or add a question. True when something changed."""
    done = False
    for part in (p.strip() for p in re.split(r",|;|\band\b", said, flags=re.I)):
        if not part:
            continue
        if _DROP.search(part):
            done = _drop(part, draft) or done
            continue
        match = _OR.search(part)
        if match:
            done = _answers(part, match, draft) or done
            continue
        if part.endswith("?") or re.match(r"^ask\b", part, re.I):
            q = part if part.endswith("?") else re.sub(r"^ask\s+", "", part, flags=re.I).capitalize() + "?"
            keep = J.ready([q], draft.get("languages") or [])["keep"]
            draft["lines"] = (draft.get("lines") or []) + keep
            done = done or bool(keep)
    return done


# ── The questions, one at a time ────────────────────────────────────────

def _more(draft: dict) -> list[tuple]:
    return [_ask("more", MORE_Q, [THATS_ALL], draft)]


def _peek(draft: dict, opener: str = PEEK) -> list[tuple]:
    notes, draft["notes"] = list(draft.get("notes") or []), []
    return [*(_say(n) for n in notes),
            _ask("peek", opener, [THATS_RIGHT, CHANGE_IT], draft, lines=_shown(draft))]


def _plan_said(said: str) -> Any:
    """The plan in the person's own words, or ``said`` itself when they
    name none (then it is a line of their own)."""
    text = said.lower()
    if re.search(r"no deadline|\bnone\b|\bno\b", text):
        return None
    for word in ("quarter", "month", "week"):
        if word in text:
            return word
    return said


def _on_plan(draft: dict, picked: str, said: str) -> list[tuple]:
    plan = PLANS[picked] if picked else _plan_said(said)
    if plan in J.SPANS or plan is None:
        draft["plan"] = plan
    else:
        _own(draft, said)
    langs = draft.get("languages") or []
    if len(langs) == 2:
        return [_ask("languages", LANGUAGES_Q.format(languages=", ".join(langs)), [J.YES, J.NO], draft)]
    return _more(draft)


def _on_languages(draft: dict, picked: str, said: str) -> list[tuple]:
    if picked == J.YES:
        draft["lines"] = (draft.get("lines") or []) + [
            {"q": J.LANGUAGES, "answers": list(draft.get("languages") or []), "multi": True}]
    elif said:
        _own(draft, said)
    return _more(draft)


def _on_more(draft: dict, _picked: str, said: str) -> list[tuple]:
    if said:
        _own(draft, said)
    return _peek(draft)


def _on_change(draft: dict, _picked: str, said: str) -> list[tuple]:
    draft["notes"] = [DONE if change(said, draft) else UNCLEAR]
    return _peek(draft, NEW_VERSION)


def _on_peek(database: Any, user_id: str, draft: dict, picked: str) -> list[tuple]:
    if picked == CHANGE_IT:
        return [_ask("change", CHANGE_Q, [], draft)]
    J.save(database, user_id, {"plan": draft.get("plan"), "lines": draft.get("lines") or []})
    if draft.get("later"):
        return [(str(uuid.uuid4()), "bot", SAVED, {"step": "saved"})]
    return [(str(uuid.uuid4()), "bot", SET, {"step": "set"})]


STEPS = {"plan": _on_plan, "languages": _on_languages, "more": _on_more, "change": _on_change}


# ── In and out ──────────────────────────────────────────────────────────

def _open_question(database: Any, user_id: str) -> Optional[dict]:
    """The setup's newest row, when it is a question still waiting."""
    for row in database.get_lounge_messages_page(str(user_id), limit=60) or []:
        setup = _setup_of(row)
        if setup:
            return row if setup.get("step") in WAITS else None
    return None


def begin(database: Any, user_id: str) -> dict:
    """The first time "Add someone to chat with" opens (N503 item 1): Will's
    first lines, or his open question again at the bottom of his chat."""
    can, value = J.kept(database, user_id)
    if not can or value is not None:
        return {"started": False}
    newest = (database.get_lounge_messages_page(str(user_id), limit=1) or [None])[0]
    if _setup_of(newest).get("step") in WAITS:
        return {"started": True}
    waiting = _open_question(database, user_id)
    if waiting:
        setup = _setup_of(waiting)
        items = [(str(uuid.uuid4()), "bot", waiting.get("body") or "", setup)]
    else:
        items = [_say(INTRO), _ask("plan", PLAN_Q, list(PLANS), _fresh(_languages(database, user_id)))]
    _write(database, user_id, items)
    return {"started": True}


def again(database: Any, user_id: str) -> dict:
    """"Your questions for people who join ›": the summary again (N503 item 2)."""
    _can, value = J.kept(database, user_id)
    if value is None:
        return begin(database, user_id)
    draft = _fresh(_languages(database, user_id), later=True)
    draft.update(plan=value.get("plan") if value.get("plan") in J.SPANS else None, lines=_own_lines(value))
    _write(database, user_id, _peek(draft, AGAIN))
    return {"started": True}


def answer(database: Any, user_id: str, payload: Any) -> dict:
    """The person's tap, or their words, under Will's question; then his next
    lines. {"messages": the rows written}."""
    body = payload if isinstance(payload, dict) else {}
    to = str(body.get("to") or "")
    setup = _setup_of(database.get_lounge_message_by_client_id(str(user_id), to) if to else None)
    step = setup.get("step")
    if step not in WAITS:
        raise JoinQuestionsError("NOT_FOUND", "No such question.", 404)
    if database.get_lounge_message_by_client_id(str(user_id), _answer_id(to)):
        raise JoinQuestionsError("ANSWERED", "Already answered.", 409)
    picked = str(body.get("picked") or "").strip()
    said = str(body.get("said") or "").strip()[:MAX_SAID]
    chips = list(setup.get("chips") or [])
    if (picked and picked not in chips) or not (picked or said) or (step == "peek" and not picked):
        raise JoinQuestionsError("PICK_ONE", "Tap one of the answers.")
    draft = {**_fresh([]), **(setup.get("draft") or {})}
    rows = (_on_peek(database, user_id, draft, picked) if step == "peek"
            else STEPS[step](draft, picked, "" if picked else said))
    mine_ = (_answer_id(to), "user", picked or said, {"step": "answer", "to": to})
    return {"messages": _write(database, user_id, [mine_, *rows])}
