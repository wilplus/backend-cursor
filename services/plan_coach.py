"""The coach's side of the plan (N213; frontend docs/flows/the-plan.md §1 C5,
G10 and H1, and docs/flows/coach-panel.md).

A plan reaches the coach's queue on the speaker's card as one of three
things, the speaker's own ask first:

  "asked"  "Ask your coach" since a coach last answered the plan (H1)
  "stuck"  three Takes on the level without moving since then (G10)
  "new"    a level the machine picked from the questions (a plan with a
           key line), which no coach has answered yet

"new" and "asked" are answered with a level, picked blind (Never 2): the
plan's payload carries the speaker's voice message and key line, never the
machine's level, which comes back only with the pick ("What happened"). The
coach's level wins and the machine never moves it (C5). "stuck" is answered
with the coach's video, shared as their word on the speaker's latest Take
(the panel's own video upload and Take word); then the plan is marked
answered. An answer takes the plan out of every coach's queue; "Audio
unclear" takes it out of this coach's only.

Who may see a plan is who may hear its speaker: a coach whose queue holds a
Take of theirs in a language the coach understands, or, for a speaker with
no Take in the queue yet, a coach who understands the language of their
voice message. Otherwise the plan is withheld, and the log names the filter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from services import plan as P
from services.plan_flow import _parse_day, _parse_dt as _when

logger = logging.getLogger(__name__)

#: What a plan waits on a coach for.
ASKED, STUCK, NEW = "asked", "stuck", "new"
#: The level events that tell the queue a plan waits.
_WAITING_REASONS = ("ask_coach", "stuck")
#: The level events by which the machine sets the level.
_MACHINE_SETS = ("diagnosis", "reached", "time")


class CoachPlanError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _facts(plan: dict) -> dict:
    return dict(plan.get("facts") or {})


def waiting(plan: dict, events: Iterable[dict]) -> Optional[tuple[str, str]]:
    """``(kind, since)`` when the plan waits on a coach, else None. ``events``:
    the plan's "ask_coach" and "stuck" events, oldest first."""
    if plan.get("status") not in ("asking", "active") or not plan.get("level"):
        return None
    facts = _facts(plan)
    answered = _when(facts.get("coach_at"))

    def last(reason: str, level: Optional[str] = None) -> Optional[str]:
        hits = [e for e in events if e.get("reason") == reason
                and (level is None or e.get("level") == level)
                and (at := _when(e.get("created_at"))) and (answered is None or at > answered)]
        return str(hits[-1]["created_at"]) if hits else None

    asked = last("ask_coach")
    if asked:
        return ASKED, asked
    stuck = last("stuck", plan.get("level"))
    if stuck:
        return STUCK, stuck
    if answered is None and plan.get("level_by") != "coach" and facts.get("key_line"):
        return NEW, str(plan.get("created_at") or "")
    return None


def _language_ok(plan: dict, proficient: Iterable[str], matched_users: set,
                 queued_users: set) -> bool:
    uid = str(plan.get("user_id") or "")
    if uid in matched_users:
        return True
    if uid in queued_users:
        return False
    return _facts(plan).get("language") in set(proficient or [])


def _unclear_for(plan: dict, rater_id: str, since: str) -> bool:
    at = _when((_facts(plan).get("coach_unclear") or {}).get(str(rater_id)))
    start = _when(since)
    return bool(at and (start is None or at >= start))


def queue_items(database: Any, *, rater_id: str, proficient: Iterable[str],
                matched_users: set, queued_users: set) -> list[dict]:
    """Every plan waiting on this coach, oldest first: ``{plan, kind, since}``.
    ``matched_users``: the speakers with a Take in this coach's queue in a
    language they understand; ``queued_users``: every speaker in the queue."""
    plans = database.list_waiting_plans() or []
    events: dict[str, list[dict]] = {}
    for e in database.list_plans_level_events([p.get("id") for p in plans], _WAITING_REASONS) or []:
        events.setdefault(str(e.get("plan_id")), []).append(e)
    out = []
    for plan in plans:
        found = waiting(plan, events.get(str(plan.get("id")), []))
        if not found:
            continue
        kind, since = found
        if not _language_ok(plan, proficient, matched_users, queued_users):
            logger.info("coach queue: plan withheld plan=%s filter=language", plan.get("id"))
            continue
        if _unclear_for(plan, rater_id, since):
            continue
        out.append({"plan": plan, "kind": kind, "since": since})
    return sorted(out, key=lambda item: item["since"])


def card(item: dict) -> dict:
    """The plan on the speaker's card: what it waits for, with the level's
    name only on a stuck level (the machine's level is never shown before
    the coach picks, Never 2) and the deadline on a new plan."""
    plan, kind = item["plan"], item["kind"]
    out: dict[str, Any] = {"plan_id": str(plan["id"]), "kind": kind, "since": item["since"]}
    if kind == STUCK:
        out["level_name"] = P.level_name(plan.get("level"))
    deadline = _parse_day(plan.get("deadline"))
    if kind == NEW and deadline:
        out["deadline_short"] = P.fmt_short(deadline)
    return out


def with_plans(queue: list[dict], items: list[dict], *, pseudonym_for: Callable[[Any], str],
               goal_for: Callable[[Any], Optional[str]]) -> list[dict]:
    """The coach's queue with each waiting plan on its speaker's card: those
    speakers first, in the order their plans wait; a speaker with no Take in
    the queue gets a card of their own."""
    by_name = {s.get("pseudonym"): s for s in queue}
    first = []
    for item in items:
        uid = item["plan"].get("user_id")
        name = pseudonym_for(uid)
        speaker = by_name.get(name)
        if speaker is None:
            speaker = {"pseudonym": name, "goal": goal_for(uid), "takes": [], "waiting": 0,
                       "waiting_for_text": 0}
            by_name[name] = speaker
        if "plan" in speaker:
            continue  # one plan per speaker
        speaker["plan"] = card(item)
        first.append(speaker)
    return first + [s for s in queue if "plan" not in s]


# ── one plan, for one coach ────────────────────────────────────────────────

def plan_for(database: Any, plan: Optional[dict], *, rater_id: str, proficient: Iterable[str],
             matched_users: set, queued_users: set, own_answer: bool = False) -> tuple[dict, Optional[str]]:
    """The plan and what it waits for, when this coach may see it. With
    ``own_answer``, also a plan this coach answered last, so that "Change my
    answer" and its players still work. 404 otherwise, saying nothing more."""
    if not plan or not _language_ok(plan, proficient, matched_users, queued_users):
        raise CoachPlanError("NOT_FOUND", "No plan waiting.", 404)
    events = database.list_plans_level_events([plan["id"]], _WAITING_REASONS) or []
    found = waiting(plan, events)
    if found:
        return plan, found[0]
    if own_answer and _facts(plan).get("coach_id") == str(rater_id):
        return plan, None
    raise CoachPlanError("NOT_FOUND", "No plan waiting.", 404)


def _answers(database: Any, plan: dict) -> list[dict]:
    return database.list_plan_answers(str(plan["user_id"]), str(plan["id"])) or []


def _voice(answer: Optional[dict]) -> Optional[dict]:
    if not answer:
        return None
    return {"answer_id": str(answer["id"]), "duration_ms": answer.get("duration_ms")}


def _key_line(plan: dict, answers: list[dict]) -> Optional[dict]:
    facts = _facts(plan)
    if not facts.get("key_line"):
        return None
    keys = [a for a in answers if a.get("kind") == "key"]
    said = next((a for a in answers if str(a.get("id")) == str(facts.get("key_answer_id"))),
                keys[-1] if keys else None)
    return {"text": facts["key_line"], **(_voice(said) or {"answer_id": None, "duration_ms": None})}


def blind(database: Any, plan: dict, kind: Optional[str], *, pseudonym: str) -> dict:
    """"Which level comes first?", or a stuck level's video screen. A level
    to pick carries the speaker's voice message and key line and the five
    levels, never the plan's level (Never 2); a stuck level carries its
    name and the Take the coach's video goes on."""
    out: dict[str, Any] = {"plan_id": str(plan["id"]), "kind": kind, "pseudonym": pseudonym}
    if kind == STUCK:
        facts = _facts(plan)
        take = facts.get("level_take")
        if not take:
            from services.plan_flow import _latest_take
            take = _latest_take(database, plan["user_id"]).get("id")
        out.update({"level_name": P.level_name(plan.get("level")),
                    "take_session_id": str(take) if take else None})
        return out
    answers = _answers(database, plan)
    # The voice message itself: a correction of it (N262) is kept as a "why"
    # too, but it is a few words, not the voice to pick a level from.
    why = [a for a in answers if a.get("kind") == "why"]
    out.update({"why": _voice(why[0] if why else None), "key_line": _key_line(plan, answers),
                "levels": [{"key": k, "name": name} for k, name in P.LEVELS.items()]})
    return out


def _latest(answers: list[dict], kind: str) -> Optional[int]:
    values = [int(a["value"]) for a in answers if a.get("kind") == kind and a.get("value") is not None]
    return values[-1] if values else None


def _machine_level(database: Any, plan: dict) -> Optional[str]:
    events = database.list_plan_level_events(str(plan["user_id"]), str(plan["id"])) or []
    mine = [e for e in events if e.get("by_who") == "machine" and e.get("reason") in _MACHINE_SETS]
    return mine[-1].get("level") if mine else None


def pick(database: Any, plan: dict, kind: Optional[str], level: Any, *, rater_id: str) -> dict:
    """The coach's level (C5): kept as the coach's, which the machine never
    moves, with a level event of its own; the plan leaves every coach's
    queue. Returns "What happened": the coach's level, the one the machine
    heard, the deadline, and the stress and readiness taps when the speaker
    gave them (N211); a level kept, never a verdict."""
    if level not in P.LEVELS:
        raise CoachPlanError("INVALID_LEVEL", "Pick one of the five levels.", 400)
    if kind == STUCK:
        raise CoachPlanError("NOT_NOW", "This plan waits for your video.", 409)
    facts = _facts(plan)
    had = list(facts.get("levels_had") or [plan.get("level")])
    fields = {"level": level, "level_by": "coach",
              "facts": {**facts, "coach_at": _now().isoformat(), "coach_id": str(rater_id),
                        "levels_had": had + ([level] if level not in had else [])}}
    if not database.update_plan(str(plan["user_id"]), str(plan["id"]), fields):
        raise CoachPlanError("V2_ERROR", "Could not keep your answer.", 500)
    database.insert_plan_level_event({"plan_id": plan["id"], "user_id": str(plan["user_id"]),
                                      "level": level, "reason": "coach", "by_who": "coach"})
    logger.info("plan: a coach picked the level plan=%s level=%s", plan.get("id"), level)
    answers = _answers(database, plan)
    machine = _machine_level(database, plan)
    deadline = _parse_day(plan.get("deadline"))
    return {
        "you": {"key": level, "name": P.level_name(level)},
        "machine": {"key": machine, "name": P.level_name(machine)} if machine else None,
        "deadline_short": P.fmt_short(deadline) if deadline else None,
        "stress": _latest(answers, "stress"),
        "ready": _latest(answers, "ready"),
        "key_line": _key_line(plan, answers),
    }


def answered(database: Any, plan: dict, kind: Optional[str], *, rater_id: str) -> dict:
    """A stuck level answered with the coach's video, already shared as
    their word on the speaker's latest Take: the plan leaves every coach's
    queue until the level is stuck again."""
    if kind not in (STUCK, None):
        raise CoachPlanError("NOT_NOW", "This plan waits for a level.", 409)
    if kind == STUCK:
        facts = {**_facts(plan), "coach_at": _now().isoformat(), "coach_id": str(rater_id)}
        if not database.update_plan(str(plan["user_id"]), str(plan["id"]), {"facts": facts}):
            raise CoachPlanError("V2_ERROR", "Could not keep your answer.", 500)
    return {"ok": True}


def unclear(database: Any, plan: dict, *, rater_id: str) -> dict:
    """"Audio unclear": the plan leaves this coach's queue, and stays in
    every other coach's."""
    facts = _facts(plan)
    facts["coach_unclear"] = {**(facts.get("coach_unclear") or {}), str(rater_id): _now().isoformat()}
    if not database.update_plan(str(plan["user_id"]), str(plan["id"]), {"facts": facts}):
        raise CoachPlanError("V2_ERROR", "Could not keep your answer.", 500)
    return {"ok": True}


def answer_audio(database: Any, plan: dict, answer_id: str) -> dict:
    """The voice message or the key line, played to the coach; no other
    answer of the plan."""
    playable = {str(a["id"]) for a in _answers(database, plan) if a.get("kind") in ("why", "key")}
    got = database.get_plan_answer_audio(str(plan["user_id"]), str(answer_id)) \
        if str(answer_id) in playable else None
    if not got:
        raise CoachPlanError("NOT_FOUND", "Not found.", 404)
    return got
