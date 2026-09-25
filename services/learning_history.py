"""The history of learning — what was said, what the coach showed, what
happened next.

FOUNDER 2026-09-25: "just make it a history of learning; there was a video
then the practice and they can scroll and actually see how it changed."

WHY THIS DISSOLVES A BUG RATHER THAN PATCHING ONE. A coach's note used to be
pinned to an exact phrase and looked up by string match, so rewriting the
sentence dropped it, silently, with nobody told. The note was trying to stay
CURRENT on words the speaker is free to change. A history entry is stamped to
a moment instead: a later rewrite cannot invalidate it, because the rewrite is
the next entry. Founder decision on the fork, same day: ANY change moves the
note into the history — strict and predictable, over a fuzzy near-match.

NOTHING NEW IS WRITTEN TO BUILD THIS. `ideal_text_versions` has snapshotted
the full text of every version since 2026-07-20, append-only; the practice row
already hangs off its take and already holds what the coach shared. This
assembles them. The snapshot table's own note reads: "each version bubble
keeps ITS OWN step readable — the text as it stood and that step's reasoning."
That was the intent; nothing ever showed them as a chain.

TWO FENCES DECIDE WHAT MAY APPEAR.

  * BLIND COACH. Only what the coach chose to SHARE reaches this history —
    `coach_shared_exercise` and the video that went with it. Their rating,
    their yes/no on the moment, their decision on a practice recording are
    judgements made blind, and they never appear here in any form.

  * AC-9. No score, ratio or verdict. The entries are facts about what
    happened: these words, this video, these recordings, these dates.

HISTORY STARTS WHERE THE TABLE STARTS. A project whose versions predate the
snapshot table has no rows, and this returns the shorter chain it can prove
rather than reconstructing one it cannot.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Fields of a practice row that are a COACH JUDGEMENT and never surface.
#: Listed rather than implied, so that adding a field to the practice table
#: cannot quietly widen what a speaker is shown.
BLIND_COACH_FIELDS = (
    "professional_coach_decision",
    "selected_attempt_coach_decision",
    "coach_rating_value",
    "machine_verdict",
)


def _rows(read: Any, *, label: str, arc_id: str) -> list:
    """One guarded list read. Anything but a list is nothing."""
    try:
        rows = read()
    except Exception:
        logger.warning("learning_history: %s unavailable arc=%s",
                       label, arc_id, exc_info=True)
        return []
    return rows if isinstance(rows, list) else []


def _text_of(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("text") or "").strip()


def _shared_coach_entry(practice: Any) -> Optional[dict]:
    """What the coach chose to show, or None.

    `coach_shared_at` is the consent: without it the coach recorded something
    for their own review and never released it, and a history that showed it
    anyway would be publishing a private note.
    """
    if not isinstance(practice, dict):
        return None
    if not practice.get("coach_shared_at"):
        return None
    shared = practice.get("coach_shared_exercise")
    if not isinstance(shared, dict):
        return None
    video = str(shared.get("explanation_video_url") or "").strip()
    title = str(shared.get("title") or "").strip()
    instruction = str(shared.get("instruction") or "").strip()
    if not (video or title or instruction):
        return None
    return {
        "title": title or None,
        "instruction": instruction or None,
        "video_ref": video or None,
        "shared_at": practice.get("coach_shared_at"),
    }


def _practice_entries(attempts: Any) -> list[dict]:
    """The speaker's own recordings, as events rather than a tally.

    Deliberately not a count: a number beside a person's attempts invites
    reading as a score, and there is nothing to score here (AC-9). What the
    history shows is that they went again, and when.
    """
    out: list[dict] = []
    for attempt in attempts if isinstance(attempts, list) else []:
        if not isinstance(attempt, dict):
            continue
        out.append({
            "attempt_index": attempt.get("attempt_index"),
            "recorded_at": attempt.get("created_at"),
        })
    return out


def build_learning_history(database: Any, arc_id: Any) -> dict:
    """The project's chain, oldest first.

    Every entry is one version: the words as they stood, what the coach
    shared on the take that produced them, and the recordings the speaker
    made afterwards. An entry with no coach and no practice is still an
    entry — the words changed, and that is the history.
    """
    project = str(arc_id or "")
    if not project:
        return {"arc_id": None, "entries": [], "history_starts_at": None}

    # Each read is guarded AND its shape checked. A reader that raises and a
    # reader that hands back something that is not a list fail the same way
    # from here -- the history simply gets shorter, never wrong, and never
    # takes the caller down with it.
    versions = _rows(lambda: database.list_ideal_text_versions(project),
                     label="versions", arc_id=project)
    sessions = _rows(lambda: database.takes.get_arc_sessions(project),
                     label="sessions", arc_id=project)
    by_take: dict[int, dict] = {}
    for session in sessions:
        if not isinstance(session, dict):
            continue
        index = session.get("take_index")
        if isinstance(index, int) and not isinstance(index, bool):
            by_take.setdefault(index, session)

    entries: list[dict] = []
    for row in versions:
        text = _text_of(row)
        if not text:
            # A snapshot with no words proves nothing and would read as a
            # blank chapter. Skip it rather than show an empty one.
            continue
        version = row.get("version")
        session = by_take.get(version) if isinstance(version, int) else None
        coach = None
        practice_entries: list[dict] = []
        if isinstance(session, dict) and session.get("id"):
            try:
                practice = database.get_confident_voice_practice_by_take(
                    str(session.get("id")))
            except Exception:
                practice = None
            coach = _shared_coach_entry(practice)
            if isinstance(practice, dict) and practice.get("id"):
                try:
                    practice_entries = _practice_entries(_rows(
                        lambda: database
                        .list_confident_voice_practice_attempts(
                            str(practice.get("id"))),
                        label="attempts", arc_id=project))
                except Exception:
                    practice_entries = []
        entries.append({
            "version": version,
            "created_at": row.get("created_at"),
            "text": text,
            "take_session_id": (
                str(session.get("id")) if isinstance(session, dict)
                and session.get("id") else None
            ),
            "coach": coach,
            "practice": practice_entries,
        })

    return {
        "arc_id": project,
        "entries": entries,
        # Named rather than implied: a project older than the snapshot table
        # has a shorter chain, and saying where it begins is the difference
        # between a short history and a wrong one.
        "history_starts_at": entries[0].get("created_at") if entries else None,
    }
