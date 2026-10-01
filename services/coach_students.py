"""The coach's students (founder 2026-10-01, Phase 0b).

Two reads the Students screens add, behind ``Config.COACH_STUDENTS_ENABLED``:

* the students' real names, for the roster and a profile. A coach knows
  their own students, so the name is not the secret here; what stays blind
  is the machine's read, and nothing in this module carries it;
* one Take loaded for the walk, so the walk can open over a Take from a
  profile exactly as it opens from the queue (the route shapes it with
  ``services.coach_moments_queue.moments_queue``).

Off, ``student_names`` is empty and ``load_walk_take`` is None, so the
routes answer as they did before the switch existed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def coach_students_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "COACH_STUDENTS_ENABLED", False))


def student_names(database: Any, user_ids: Any) -> dict[str, str]:
    """{user_id: name} for the students who have one on file; {} when the
    switch is off, when none is given, or when the read fails."""
    if not coach_students_enabled():
        return {}
    ids = [str(u) for u in (user_ids or []) if u]
    if not ids:
        return {}
    try:
        return database.get_student_names(ids) or {}
    except Exception as error:
        logger.warning("coach students: names unreadable: %s", error, exc_info=True)
        return {}


def name_field(names: dict[str, str], user_id: Any) -> dict:
    """``{"name": ...}`` when the student has one, else nothing: the row
    never carries a name key the switch did not earn."""
    name = (names or {}).get(str(user_id or ""))
    return {"name": name} if name else {}


def load_walk_take(database: Any, session_id: str, rater_id: str) -> Optional[dict]:
    """Everything the walk-take route needs for one Take, in one place, or
    None when the switch is off or the Take does not exist."""
    if not coach_students_enabled():
        return None
    row = database.v2_get_session_by_id(str(session_id))
    if not row or not row.get("id"):
        return None
    sid = str(row["id"])
    user_id = str(row.get("user_id") or "")
    return {
        "row": row,
        "snippets": database.get_snippets_by_session(sid) or [],
        "ratings": database.get_own_state_ratings_for_session(sid, rater_id) or {},
        "requests": database.list_exercise_coach_requests_for_sessions([sid]) or {},
        "proficient": database.get_user_proficient_languages(rater_id),
        "name": student_names(database, [user_id]).get(user_id),
    }
