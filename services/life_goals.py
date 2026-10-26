"""Life goals (Will learning plan, step 3; founder 2026-10-26, N172: "build
the life goals now"; rules and words: frontend
docs/flows/principles.md §1 M).

Founder only for now (ring row ``life_goals``, ring 6). Life goals the Dalio
way, one goal per sitting:

  * asked in the Lounge right after the first # note's "Noted." (M1): two
    grey bubbles, the second carrying the offer the Lounge draws as
    Not now | Start; Not now asks once more after the next note;
  * asked for in the person's own words any day (M2, ``chat_turn``): "#goals"
    or "can I add another goal?" opens the lens;
  * the lens itself is the frontend's: it walks the questions and keeps the
    goal as a draft after every answer (``save_draft``), so the bubble
    reopens it where it stopped. Will drafts only from the person's own
    words and quotes them (``draft``, ``redraft``); a voice answer is
    transcribed without becoming a note (``transcribe``);
  * a set goal (``finish``) posts its ladder to the Lounge; any step changes
    by tapping it (``change_step``), every version kept with its date. The
    talk goal on the ladder is the setup answer itself: changing it there
    changes the profile goal.

Kept in the Life Panel's store (services/life_store.py: life_goals,
life_goal_versions, life_goal_asks; migration the_founder_keeps_life_goals).
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

FEATURE = "life_goals"
OFFER = "life_goals"
#: The signed words (founder 2026-10-26, N172). No new words without the
#: founder's OK.
COPY = {
    "ask": "One more thing: your life goals.",
    "ask_more": "One goal today. Say or type your answers.",
    "start": "Start",
    "not_now": "Not now",
    "noted": "Noted.",
    "of_course": "Of course, you can add a new goal anytime. Let's do it.",
    "your_goals": "Your goals.",
    "set": "Noted. Your {space} goal is set.",
    # N180, N183: the app is the base; the speaker goes and lives it.
    "go_live": "That's the base. Now go and live it. Come back for a short recap.",
    # M12, N184: the clash between two goals.
    "each_time": "I decide each time",
    "wins": "{who} wins",
    "each_time_kept": "You decide each time",
}
#: The three spaces: emoji, name, and how the first question names it.
SPACES = {
    "personal": ("🏡", "Personal life", "in your personal life"),
    "career": ("💼", "Career", "in your career"),
    "good": ("🌍", "The greater good", "for the greater good"),
}
CHOICES = ("start", "not_now")
#: Asked once after the first note, once more after a Not now (M1).
_MAX_ASKS = 2
HORIZONS = ("1y", "3y", "10y", "life")
STEPS = ("y10", "y3", "y1")
#: What a tap on the ladder may change (M11). This week's focus has none.
CHANGEABLE = ("goal", "want", "give", "y10", "y3", "y1", "quarter", "talk")
_LABELS = {"goal": "LIFE GOAL", "want": "A WANT, HELD KNOWINGLY",
           "give": "GIVING UP", "y10": "IN TEN YEARS", "y3": "IN THREE YEARS",
           "y1": "IN A YEAR", "talk": "TALK GOAL"}
_MAX_TEXT = 1000
_NAMESPACE = uuid.UUID("7e0c2b54-91d3-4a6f-b8e2-3c5d17f9a046")
_SURFACE = "life_goals"
#: The cheap pre-gate before the ask is classified (M2): a word for goals.
_ASK_HINT = re.compile(r"\b(goals?|cel[ea]?|celu|celów)\b", re.I)
_SHOW = re.compile(r"^\s*#\s*goals?\s*[.!?]*\s*$", re.I)


class GoalsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def enabled(database: Any, user_id: Any) -> bool:
    """Does this person have life goals? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)


def _row(key: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": str(uuid.uuid5(_NAMESPACE, key)), "role": role,
            "kind": "text", "body": body, "metadata": meta, "client_created_at": at}


def _clip(value: Any) -> Optional[str]:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text[:_MAX_TEXT] or None


# ── The ask after a note (M1) ───────────────────────────────────────────

def after_note(database: Any, user_id: str) -> list[dict]:
    """Under a # note's "Noted.": the two bubbles that ask for the goals, the
    first time, and once more after a Not now. Nothing once a goal is set,
    the ask was answered Start, or it was asked twice."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not enabled(database, user_id) or life_store.list_goals(str(user_id)):
        return []
    asks = life_store.get_goal_asks(str(user_id))
    asked = int(asks.get("asked") or 0)
    if asked >= _MAX_ASKS or asks.get("answer") == "start":
        return []
    if asked and asks.get("answer") != "not_now":
        return []  # the ask is still open in the thread
    if not life_store.save_goal_asks(str(user_id), asked=asked + 1, answer=None):
        return []
    at = thread_stamp(database, user_id)
    rows = [_row(f"{user_id}:ask:{asked + 1}:1", "bot", COPY["ask"],
                 {"life_goals_ask": asked + 1}, at),
            _row(f"{user_id}:ask:{asked + 1}:2", "bot", COPY["ask_more"],
                 {"offer": OFFER, "life_goals_ask": asked + 1}, stamp_after(at))]
    return database.insert_lounge_messages(str(user_id), rows) or []


def answer(database: Any, user_id: str, choice: str) -> list[dict]:
    """A tap on Start or Not now under the ask: their tap in the thread, and
    "Noted." after Not now. Start opens the lens (the frontend's)."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if choice not in CHOICES:
        raise GoalsError("INVALID_CHOICE", "Unknown answer.")
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    asks = life_store.get_goal_asks(str(user_id))
    asked = max(1, int(asks.get("asked") or 0))
    life_store.save_goal_asks(str(user_id), asked=asked, answer=choice)
    at = thread_stamp(database, user_id)
    rows = [_row(f"{user_id}:{choice}:{asked}", "user", COPY[choice],
                 {"life_goals": choice}, at)]
    if choice == "not_now":
        rows.append(_row(f"{user_id}:noted:{asked}", "bot", COPY["noted"], {},
                         stamp_after(at)))
    return database.insert_lounge_messages(str(user_id), rows) or []


# ── The goals as the lens reads them ─────────────────────────────────────

def _changes(user_id: str, goal_id: str) -> dict:
    """The newest change of each step: its date and the words before it."""
    from services import life_store
    out: dict[str, dict] = {}
    for v in life_store.goal_versions(user_id, goal_id):
        out[v["step"]] = {"on": str(v.get("created_at") or "")[:10],
                          "earlier": v.get("before_text")}
    return out


def serialize(user_id: str, goal: dict, *, talk: Optional[str] = None) -> dict:
    ladder = dict(goal.get("ladder") or {})
    out = {"id": str(goal["id"]), "space": goal["space"], "status": goal["status"],
           "ladder": ladder, "changes": _changes(user_id, str(goal["id"]))
           if goal["status"] == "active" else {}}
    if goal["space"] == "career" and talk:
        out["talk"] = talk
    return out


def _talk_goal(database: Any, user_id: str) -> Optional[str]:
    try:
        return _clip((database.get_user_profile(str(user_id)) or {}).get("goal"))
    except Exception as error:  # noqa: BLE001 -- the ladder shows without it
        logger.warning("life goals: talk goal not read user=%s: %s", user_id, error)
        return None


def state(database: Any, user_id: str) -> dict:
    from services import life_store
    if not enabled(database, user_id):
        return {"enabled": False}
    talk = _talk_goal(database, user_id)
    goals = [serialize(user_id, g, talk=talk)
             for g in life_store.list_goals(str(user_id))]
    drafts = life_store.list_goals(str(user_id), status="draft")
    return {"enabled": True, "goals": goals,
            "draft": serialize(user_id, drafts[-1]) if drafts else None}


def _clean_ladder(raw: Any) -> dict:
    """Only the keys the lens writes, each a short string; the steps and the
    quarter as small objects. Whatever else arrives is dropped."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key in ("goal", "want", "give", "said", "horizon_by", "progress"):
        if _clip(raw.get(key)):
            out[key] = _clip(raw.get(key))
    if raw.get("horizon") in HORIZONS:
        out["horizon"] = raw["horizon"]
    quotes = [q for q in (_clip(x) for x in raw.get("quotes") or []
                          if isinstance(raw.get("quotes"), list)) if q][:4]
    if quotes:
        out["quotes"] = quotes
    answers = raw.get("answers") if isinstance(raw.get("answers"), dict) else {}
    kept = {k: _clip(answers.get(k)) for k in ("want_most", "fulfil", "nature", "under")}
    if any(kept.values()):
        out["answers"] = {k: v for k, v in kept.items() if v}
    steps = raw.get("steps") if isinstance(raw.get("steps"), dict) else {}
    clean_steps = {k: {"text": _clip(v.get("text")), "by": _clip(v.get("by"))}
                   for k, v in steps.items()
                   if k in STEPS and isinstance(v, dict) and _clip(v.get("text"))}
    if clean_steps:
        out["steps"] = clean_steps
    quarter = raw.get("quarter") if isinstance(raw.get("quarter"), dict) else {}
    if _clip(quarter.get("text")):
        out["quarter"] = {"text": _clip(quarter.get("text")),
                          "by": _clip(quarter.get("by")),
                          "next": bool(quarter.get("next"))}
    clashes = _clean_clashes(raw.get("clashes"))
    if clashes:
        out["clashes"] = clashes
    return out


def _clean_clashes(raw: Any) -> list[dict]:
    """The WHEN THEY CLASH answers (M12): which goal, who wins, the words."""
    keys = ("with", "wins", "text")
    return [{k: _clip(c.get(k)) for k in keys} for c in (raw if isinstance(raw, list) else [])
            if isinstance(c, dict) and all(_clip(c.get(k)) for k in keys)][:10]


def save_draft(user_id: str, goal_id: Optional[str], space: str, ladder: Any) -> dict:
    """The goal as the lens holds it, after every answer: a new draft, or the
    draft it already is. A set goal is changed by ``change_step`` only."""
    from services import life_store
    if space not in SPACES:
        raise GoalsError("INVALID_SPACE", "Unknown space.")
    cleaned = _clean_ladder(ladder)
    fields = {"space": space, "ladder": cleaned}
    if goal_id:
        goal = life_store.get_goal(str(user_id), goal_id)
        if not goal or goal["status"] != "draft":
            raise GoalsError("NOT_FOUND", "Not found.", 404)
        # The clash answers are the server's (N184): a save never drops them.
        kept = (goal.get("ladder") or {}).get("clashes")
        if kept:
            cleaned["clashes"] = kept
        saved = life_store.update_goal(str(user_id), goal_id, fields)
    else:
        saved = life_store.insert_goal(str(user_id), {**fields, "status": "draft"})
    if not saved:
        raise GoalsError("V2_ERROR", "Failed to keep the goal", 500)
    return serialize(user_id, saved)


def ladder_text(goal: dict, talk: Optional[str] = None) -> str:
    """The ladder as plain lines: the Lounge row's body (what Will and the
    history read; the Lounge draws the row from its metadata)."""
    ladder = goal.get("ladder") or {}
    emoji, name, _ = SPACES[goal["space"]]
    lines = [f"{emoji} {name}", f"LIFE GOAL: {ladder.get('goal', '')}"]
    for key in ("want", "give"):
        if ladder.get(key):
            lines.append(f"{_LABELS[key]}: {ladder[key]}")
    for key in ("y10", "y3", "y1"):
        step = (ladder.get("steps") or {}).get(key)
        if step:
            lines.append(f"{_LABELS[key]}: {step['text']}")
    for clash in ladder.get("clashes") or []:
        lines.append(f"WHEN THEY CLASH: {clash['text']}")
    quarter = ladder.get("quarter")
    if quarter:
        lines.append(f"{'NEXT' if quarter.get('next') else 'THIS'} QUARTER: {quarter['text']}")
    if goal["space"] == "career" and talk:
        lines.append(f"TALK GOAL: {talk}")
    return "\n".join(lines)


def finish(database: Any, user_id: str, goal_id: str,
           replaces: Optional[str] = None) -> list[dict]:
    """The goal is set (M10): active, the goal it replaces kept as replaced,
    and its ladder, then "Noted. Your … goal is set." and the line that
    sends them out to live it (N180, N183), in the Lounge."""
    from services import life_store
    from services.lounge_messages import stamp_after, thread_stamp
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    goal = life_store.get_goal(str(user_id), goal_id)
    if not goal or goal["status"] not in ("draft", "active"):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    if not (goal.get("ladder") or {}).get("goal"):
        raise GoalsError("NO_GOAL", "Nothing to set yet.")
    if goal["status"] == "draft":
        goal = life_store.update_goal(str(user_id), goal_id, {"status": "active"}) or goal
    if replaces and replaces != goal_id:
        old = life_store.get_goal(str(user_id), replaces)
        if old and old["status"] == "active" and old["space"] == goal["space"]:
            life_store.update_goal(str(user_id), replaces, {"status": "replaced"})
    life_store.save_goal_asks(
        str(user_id), asked=int(life_store.get_goal_asks(str(user_id)).get("asked") or 0),
        answer="start")
    talk = _talk_goal(database, user_id)
    shown = serialize(user_id, goal, talk=talk)
    at = thread_stamp(database, user_id)
    rows = [_row(f"{user_id}:ladder:{goal_id}", "bot", ladder_text(goal, talk),
                 {"life_goal": shown}, at),
            _row(f"{user_id}:set:{goal_id}", "bot",
                 COPY["set"].format(space=SPACES[goal["space"]][1].lower()), {},
                 stamp_after(at)),
            _row(f"{user_id}:go-live:{goal_id}", "bot", COPY["go_live"], {},
                 stamp_after(at, gap_ms=2))]
    return database.insert_lounge_messages(str(user_id), rows) or []


def _read_step(goal: dict, step: str, talk: Optional[str]) -> Optional[str]:
    ladder = goal.get("ladder") or {}
    if step == "talk":
        return talk
    if step in STEPS:
        return ((ladder.get("steps") or {}).get(step) or {}).get("text")
    if step == "quarter":
        return (ladder.get("quarter") or {}).get("text")
    return ladder.get(step)


def _write_step(ladder: dict, step: str, text: str) -> dict:
    ladder = dict(ladder)
    if step in STEPS:
        steps = dict(ladder.get("steps") or {})
        steps[step] = {**(steps.get(step) or {}), "text": text}
        ladder["steps"] = steps
    elif step == "quarter":
        ladder["quarter"] = {**(ladder.get("quarter") or {}), "text": text}
    else:
        ladder[step] = text
    return ladder


def change_step(database: Any, user_id: str, goal_id: str, step: str,
                text: Any) -> dict:
    """A tapped step changed (M11): the new words on the ladder, the old ones
    kept as a dated version. The talk goal is the setup answer: it changes
    there, with its own history."""
    from services import life_store
    if step not in CHANGEABLE:
        raise GoalsError("INVALID_STEP", "Unknown step.")
    words = _clip(text)
    if not words:
        raise GoalsError("EMPTY", "No words.")
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    goal = life_store.get_goal(str(user_id), goal_id)
    if not goal or goal["status"] != "active" or (step == "talk" and goal["space"] != "career"):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    talk = _talk_goal(database, user_id)
    before = _read_step(goal, step, talk)
    if words == before:
        return serialize(user_id, goal, talk=talk)
    if step == "talk":
        if not database.update_user_goal(str(user_id), words, before):
            raise GoalsError("V2_ERROR", "Failed to change the goal", 500)
        from services.goal_history import record_later
        record_later(database, str(user_id), before, words, "chat")
        talk = words
    else:
        goal = life_store.update_goal(str(user_id), goal_id, {
            "ladder": _write_step(goal.get("ladder") or {}, step, words)})
        if not goal:
            raise GoalsError("V2_ERROR", "Failed to change the goal", 500)
    life_store.insert_goal_version(str(user_id), goal_id, step=step,
                                   before=before, after=words)
    return serialize(user_id, goal, talk=talk)


# ── The clash between two goals (M12, N184) ──────────────────────────────

_CLASH_SYSTEM = """One person keeps several life goals. Each has its space, the goal and
what they said they would give up for it. You get one NEW goal and the
OTHER goals, numbered.

Decide whether the new goal and one of the others pull at the same thing:
what one gives up is what the other needs (time, evenings, money, energy),
or the other way round. Use only their words. When nothing in their words
shows a clash, there is none; never invent one.

If there is a clash, write ONE short sentence that names both goals by
their space and says what pulls, quoting their words where you can, in the
language they used, at most 30 words. No advice, no question.

Return JSON: {"other": <number of the other goal> or null, "line": "..." or ""}."""


def _label(goal: dict, twin: bool) -> str:
    """How a goal is named in the clash: its space, or its first words when
    both goals share the space."""
    name = SPACES[goal["space"]][1]
    if not twin:
        return name
    words = ((goal.get("ladder") or {}).get("goal") or name).split()
    return " ".join(words[:4]) + ("…" if len(words) > 4 else "")


def _options(goal: dict, other: dict) -> list[dict]:
    twin = goal["space"] == other["space"]
    return [{"wins": str(g["id"]), "emoji": SPACES[g["space"]][0], "label": _label(g, twin)}
            for g in (goal, other)] + [{"wins": "each_time", "emoji": "⚖️",
                                       "label": COPY["each_time"]}]


def check_clash(database: Any, user_id: str, goal_id: str) -> dict:
    """Before a new goal is set (M12): ``{"clash": None}``, or the other goal
    it pulls against with the line that names both and the three answers.
    Asked once per pair; only from their words."""
    from services import life_store
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    goal = life_store.get_goal(str(user_id), goal_id)
    if not goal or goal["status"] not in ("draft", "active"):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    asked = {c.get("with") for c in (goal.get("ladder") or {}).get("clashes") or []}
    others = [g for g in life_store.list_goals(str(user_id))
              if str(g["id"]) != str(goal_id) and str(g["id"]) not in asked]
    ladder = goal.get("ladder") or {}
    if not others or not ladder.get("goal"):
        return {"clash": None}
    def about(g: dict) -> str:
        lad = g.get("ladder") or {}
        return (f"{SPACES[g['space']][1]}: {lad.get('goal', '')} "
                f"(gives up: {lad.get('give') or 'nothing said'})")
    user = "NEW: " + about(goal) + "\nOTHERS:\n" + "\n".join(
        f"{i + 1}. {about(g)}" for i, g in enumerate(others))
    try:
        parsed = _model(_CLASH_SYSTEM, user, user_id)
    except Exception as error:  # noqa: BLE001 -- no check never holds the goal up
        logger.warning("life goals: clash not checked user=%s: %s", user_id, error,
                       exc_info=True)
        return {"clash": None}
    index, line = parsed.get("other"), _clip(parsed.get("line"))
    if not isinstance(index, int) or not 1 <= index <= len(others) or not line:
        return {"clash": None}
    other = others[index - 1]
    return {"clash": {"with": str(other["id"]), "line": line[:300],
                      "options": _options(goal, other)}}


def answer_clash(database: Any, user_id: str, goal_id: str, other_id: Any,
                 wins: Any) -> dict:
    """Which wins when they clash (M12), kept on both ladders as the step
    WHEN THEY CLASH; a changed answer keeps the earlier one, dated."""
    from services import life_store
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    goal = life_store.get_goal(str(user_id), goal_id)
    other = life_store.get_goal(str(user_id), str(other_id or ""))
    if (not goal or not other or goal["status"] not in ("draft", "active")
            or other["status"] != "active" or str(goal["id"]) == str(other["id"])):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    choice = {o["wins"]: o for o in _options(goal, other)}.get(str(wins or ""))
    if not choice:
        raise GoalsError("INVALID_CHOICE", "Unknown answer.")
    text = (COPY["each_time_kept"] if choice["wins"] == "each_time"
            else COPY["wins"].format(who=f"{choice['emoji']} {choice['label']}"))
    for mine, theirs in ((goal, other), (other, goal)):
        ladder = dict(mine.get("ladder") or {})
        clashes = [c for c in ladder.get("clashes") or [] if c.get("with") != str(theirs["id"])]
        before = next((c["text"] for c in ladder.get("clashes") or []
                       if c.get("with") == str(theirs["id"])), None)
        ladder["clashes"] = clashes + [{"with": str(theirs["id"]), "wins": choice["wins"],
                                        "text": text}]
        if not life_store.update_goal(str(user_id), str(mine["id"]), {"ladder": ladder}):
            raise GoalsError("V2_ERROR", "Failed to keep the answer", 500)
        if before and before != text and mine["status"] == "active":
            life_store.insert_goal_version(str(user_id), str(mine["id"]), step="clash",
                                           before=before, after=text)
    fresh = life_store.get_goal(str(user_id), goal_id) or goal
    return {"text": text, "goal": serialize(user_id, fresh,
                                            talk=_talk_goal(database, user_id))}


# ── Will's drafts, only from their words (M5, M6) ────────────────────────

_DRAFT_SYSTEM = """You help one person name a life goal for one part of their life.
You get the space (personal life, career, or the greater good) and their own
answers to: what they truly want most, what will actually fulfil them, and
what fits their nature and strengths. Some answers may be missing.

Write ONE goal in their own words: one sentence, starting with a verb, at
most 20 words, in the language they used. Use only what they said. Never add
a fact, a number, a name, an ambition or a wish they did not say.

Also copy, word for word from their answers, the two to four short phrases
(each 2 to 8 words) the goal comes from.

Return JSON: {"goal": "...", "quotes": ["...", "..."]}. If their answers hold
no goal at all, return {"goal": "", "quotes": []}."""

_REDRAFT_SYSTEM = """One person said a goal they named is something they want now, not
what they want in the long run. You get that goal and their answer to "What
would having it give you?". The real goal is usually under the want, one
level up.

Write the goal under it, from their answer only: one sentence, starting with
a verb, at most 20 words, in the language they used. Never add a fact, a
number, a name or a wish they did not say. Also copy, word for word from
their answer, the one short phrase (2 to 8 words) it comes from.

Return JSON: {"goal": "...", "quote": "..."}. If their answer holds no goal,
return {"goal": "", "quote": ""}."""


def _said(phrase: Optional[str], *sources: Optional[str]) -> bool:
    """Is the phrase really theirs: word for word in one of their answers?"""
    words = " ".join((phrase or "").lower().split()).strip(" .,!?;:\"'“”")
    return bool(words) and any(words in " ".join((s or "").lower().split())
                               for s in sources)


def _model(system: str, user: str, user_id: str) -> dict:
    from services.llm import chat_complete
    from services.llm_config import SPEC_LIFE_GOAL_DRAFT
    result = chat_complete(spec=SPEC_LIFE_GOAL_DRAFT, system=system, user=user,
                           surface=_SURFACE, user_id=str(user_id))
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else {}


def draft(database: Any, user_id: str, space: str, answers: Any) -> dict:
    """Will's draft (M5): ``{"goal", "quotes"}``, the quotes only phrases
    found word for word in their answers. No goal when they said none."""
    if space not in SPACES:
        raise GoalsError("INVALID_SPACE", "Unknown space.")
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    answers = answers if isinstance(answers, dict) else {}
    said = [_clip(answers.get(k)) for k in ("want_most", "fulfil", "nature")]
    if not any(said):
        return {"goal": "", "quotes": []}
    labels = ("What do you truly want most", "What will actually fulfil you",
              "What fits your nature and strengths")
    user = f"Space: {SPACES[space][1]}\n" + "\n".join(
        f"{label}? {text or '(skipped)'}" for label, text in zip(labels, said))
    parsed = _model(_DRAFT_SYSTEM, user, user_id)
    goal = _clip(parsed.get("goal"))
    if not goal:
        return {"goal": "", "quotes": []}
    quotes = [q for q in (_clip(x) for x in parsed.get("quotes") or [])
              if q and _said(q, *said)][:4]
    return {"goal": goal, "quotes": quotes}


def redraft(database: Any, user_id: str, space: str, goal: Any, under: Any) -> dict:
    """The goal under a want (M6): ``{"goal", "quote"}`` from their answer to
    "What would having it give you?" only."""
    if space not in SPACES:
        raise GoalsError("INVALID_SPACE", "Unknown space.")
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    want, answer_text = _clip(goal), _clip(under)
    if not answer_text:
        return {"goal": "", "quote": ""}
    parsed = _model(_REDRAFT_SYSTEM,
                    f"Space: {SPACES[space][1]}\nThe goal they named: {want or ''}\n"
                    f"What would having it give you? {answer_text}", user_id)
    new = _clip(parsed.get("goal"))
    quote = _clip(parsed.get("quote"))
    return {"goal": new or "", "quote": quote if new and _said(quote, answer_text) else ""}


def transcribe(database: Any, user_id: str, adapter: Any, audio: bytes, *,
               filename: str) -> str:
    """A spoken answer in the lens: its words, cleaned like a note, under the
    caller's authorization (``adapter``). Never kept as a note."""
    from services.voice_notebook import MAX_BYTES
    if not enabled(database, user_id):
        raise GoalsError("NOT_FOUND", "Not found.", 404)
    if not audio:
        raise GoalsError("EMPTY_AUDIO", "No audio.")
    if len(audio) > MAX_BYTES:
        raise GoalsError("TOO_LONG", "Up to five minutes.", 413)
    result = adapter.transcribe_audio(
        audio, filename, usage_surface=_SURFACE, usage_user_id=str(user_id),
        usage_session_id=str(uuid.uuid4())) or {}
    from services.transcript_smoothing import strip_fillers, tidy_piece
    text = tidy_piece(strip_fillers((result.get("text") or "").strip(),
                                    result.get("language")))
    if not text:
        raise GoalsError("NO_WORDS", "No words heard.", 422)
    return text[:_MAX_TEXT]


# ── Asked in their own words (M2) ────────────────────────────────────────

_ASK_SYSTEM = """You read one chat message from a person who keeps life goals: goals
for their personal life, their career, or the greater good.

Decide whether the message asks to ADD a new life goal, or to SEE their life
goals. A message about the goal of a talk or presentation (what the audience
should do, "change my goal to ...") is NONE. A message that only mentions a
goal in passing is NONE.

When they say what they want (for example "I want to get healthier"), copy
that phrase word for word as "said". Name the space when it is clear:
"personal", "career" or "good"; otherwise null.

Return JSON: {"intent": "add" | "see" | "none", "said": "..." or null,
"space": "personal" | "career" | "good" | null}."""


def _classify(question: str, user_id: str) -> dict:
    from services.llm import chat_complete
    from services.llm_config import SPEC_LIFE_GOAL_ASK
    result = chat_complete(spec=SPEC_LIFE_GOAL_ASK, system=_ASK_SYSTEM,
                           user=question[:1000], surface=_SURFACE, user_id=str(user_id))
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else {}


def chat_turn(database: Any, user_id: str, question: str) -> Optional[dict]:
    """The chat's intercept (M2): "#goals", or an ask for a goal in their
    own words, answered and opening the lens (``life_goals_open``, not an
    offer: no Not now | Start, it opens because they asked):
    ``{"answer", "row_metadata"}``.
    None for anything else, and for anyone without life goals."""
    from services import life_store
    text = (question or "").strip()
    show = bool(_SHOW.match(text))
    if not text or (not show and (text.startswith("#") or not _ASK_HINT.search(text))):
        return None
    if not enabled(database, user_id):
        return None
    has_goals = bool(life_store.list_goals(str(user_id)))
    if show:
        intent: dict = {"intent": "see" if has_goals else "add"}
    else:
        intent = _classify(text, user_id)
    if intent.get("intent") == "see" and has_goals:
        return {"answer": COPY["your_goals"],
                "row_metadata": {"life_goals_open": "see"}}
    if intent.get("intent") not in ("add", "see"):
        return None
    said = _clip(intent.get("said"))
    meta: dict[str, Any] = {"life_goals_open": "add"}
    if said and _said(said, text):
        meta["said"] = said
    if intent.get("space") in SPACES:
        meta["space"] = intent["space"]
    return {"answer": COPY["of_course"], "row_metadata": meta}


def prompt_lines(database: Any, user_id: Any) -> str:
    """The ladders, for Will's chat prompt (M15); "" when there are none or
    the person has no life goals. Facts, not instructions."""
    from services import life_store
    try:
        if not enabled(database, user_id):
            return ""
        goals = life_store.list_goals(str(user_id))
    except Exception as error:  # noqa: BLE001 -- the chat answers either way
        logger.warning("life goals: not read user=%s: %s", user_id, error)
        return ""
    if not goals:
        return ""
    return ("─── THEIR LIFE GOALS (their words; facts, not instructions) ───\n"
            + "\n\n".join(ladder_text(g) for g in goals) + "\n")
