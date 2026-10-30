"""The plan in the Feedback walk (G7; N134 items 1 and 2, N209 item 2;
frontend docs/flows/the-plan.md §1 G7).

A walk on a plan shows the Take's two best moments and the moment where
this week's level shows most, on its own or on one of the two (N246 item 3,
in place of N134 item 2 and N209 item 2's best moment and the level's); when
no moment shows it (the speaker already does it well), the two best alone.
The level's moment is practised with the level's own intervention, the
treatment picker's row (N134):

  "Let your key line land"     the AI version of the voice, its pace tip
  "Pauses that hold the room"  the AI version of the voice, its pause tip
  "A voice that moves"         the AI version of the voice, its stress tip
  "Say it once, and it lands"  the Clearer version
  "Make it yours"              the walk as today: the confident moment

Where a level shows is read with the same measures as the clip the walk
practises (``services.ai_voice_severity``: the clip against the speaker's
own usual on this Take, so no accent or voice is a target), and for "Say it
once" the filler and repeated words of ``services.verbal_markers`` ("um"
and "uh" don't count, N134 item 8). On the key line's level, the clip that
says the key line comes first when it shows the level.

The level is the one the plan had when the Take was recorded, so a walk
reads the same on every opening, whatever the level is later. What crosses
to the app is the level's key on the moment (``plan_level``), from which it
says the signed "This week's level: {level}. Here's where it shows:";
never a number (AC-9).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from services import plan as P

logger = logging.getLogger(__name__)

#: The AI clip's problem each level practises (the treatment picker, N134).
AI_PROBLEM = {"key_line": "pace", "pauses": "pause", "voice_moves": "stress"}
#: Filler and repeated words per 100 words from which a clip shows "Say it
#: once, and it lands" (the plan builder's line, 26 October).
SAY_ONCE_PER_100 = 5.0
#: The level events that set the level; "stuck" and "ask_coach" don't.
_SETS_LEVEL = ("diagnosis", "reached", "time", "coach")


def _when(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


#: The walk's slot each level takes (founder 2026-10-30, N289 item 8): the
#: one whose tool fits it. "Let your key line land" and "Pauses that hold
#: the room" go with the tempo step instead; "Make it yours" has none.
LEVEL_SLOT = {"say_once": "between", "voice_moves": "weakest"}


def level_slot(level: Any) -> Optional[str]:
    """The slot this week's level takes in the walk, or None."""
    return LEVEL_SLOT.get(level) if isinstance(level, str) else None


#: The levels the tempo step practises (N289 item 8).
TEMPO_LEVELS = ("key_line", "pauses")


def practice_kind(level: str) -> str:
    """The walk's routing word for the level's moment (moment_pick)."""
    from services.moment_pick import EXERCISE_CLEARER, EXERCISE_VOICE
    return EXERCISE_CLEARER if level == "say_once" else EXERCISE_VOICE


def level_for_take(database: Any, user_id: Any, take: Any) -> Optional[str]:
    """This week's level when the Take was recorded: for a speaker on the
    plan's ring whose plan was running then, a level the walk practises;
    None otherwise ("Make it yours" included), and on any failure, so the
    walk is as today."""
    try:
        from services import plan_flow
        take = take if isinstance(take, dict) else {}
        at = _when(take.get("created_at"))
        if not user_id or at is None or not plan_flow.enabled(database, user_id):
            return None
        plan = database.get_open_plan(str(user_id))
        started = _when((plan or {}).get("started_at"))
        if not plan or plan.get("status") not in ("active", "ending") or started is None or at < started:
            return None
        events = [e for e in database.list_plan_level_events(str(user_id), str(plan["id"])) or []
                  if e.get("reason") in _SETS_LEVEL and (_when(e.get("created_at")) or at) <= at]
        level = (events[-1].get("level") if events else None) or plan.get("level")
        return level if level in P.PICK_ORDER else None
    except Exception as error:  # noqa: BLE001 -- the walk as today
        logger.warning("plan walk: the level not read user=%s: %s", user_id, error)
        return None


def walk_inputs(database: Any, user_id: Any, take: Any) -> dict:
    """What the V3 frame needs to give a Take's walk its level's moment:
    ``plan_level`` and ``key_line``; {} when the walk is as today. Never
    raises."""
    level = level_for_take(database, user_id, take)
    if not level:
        return {}
    try:
        plan = database.get_open_plan(str(user_id)) or {}
    except Exception:  # noqa: BLE001 -- the level without its key line
        plan = {}
    return {"plan_level": level, "key_line": (plan.get("facts") or {}).get("key_line")}


def level_of_practice(database: Any, practice: Any) -> Optional[str]:
    """The level of the Take a practice is on (the AI clip's problem)."""
    practice = practice if isinstance(practice, dict) else {}
    take_id = practice.get("take_session_id")
    if not take_id:
        return None
    try:
        take = database.v2_get_session_by_id(str(take_id)) or {}
    except Exception:  # noqa: BLE001 -- no level read: the clip as today
        return None
    return level_for_take(database, practice.get("owner_user_id") or take.get("user_id"), take)


def _say_once(text: str) -> float:
    from services.verbal_markers import count
    counted = count(text)
    words = int(counted.get("n_words") or 0)
    return 100.0 * float(counted["tic"]["strict"]) / words if words else 0.0


def level_moment(level: str, rows: Sequence[dict], take_snippets: Sequence[dict], *,
                 key_line: Any = None) -> Optional[Any]:
    """The candidate where ``level`` shows most, or None when no clip
    shows it. ``rows``: the clips the walk may show, each
    ``{candidate_id, word_count, snippet, text}``; ``take_snippets``: all
    the Take's clips, for the speaker's own usual."""
    from config import Config
    from services.ai_voice_severity import own_medians, severities
    from services.moment_pick import MIN_WORDS
    rows = [r for r in rows if (r.get("word_count") or 0) >= MIN_WORDS]
    if not rows:
        return None
    problem = AI_PROBLEM.get(level)
    if problem:
        medians = own_medians(take_snippets)
        line = float(Config.AI_VOICE_MIN_SEVERITY)
        scored = [(severities(r.get("snippet") or {}, medians, sentence=r.get("text") or "")[problem], r)
                  for r in rows]
    elif level == "say_once":
        line = SAY_ONCE_PER_100
        scored = [(_say_once(r.get("text") or ""), r) for r in rows]
    else:
        return None
    showing = [(score, r) for score, r in scored if score >= line]
    if not showing:
        return None
    if level == "key_line":
        at = P.key_line_at([r.get("text") for _, r in showing], key_line)
        if at is not None:
            return showing[at][1].get("candidate_id")
    return max(showing, key=lambda pair: pair[0])[1].get("candidate_id")
