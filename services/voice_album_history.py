"""The history behind one Voice Album moment (founder 2026-09-18).

"I want the whole history so I can see from where it came from and the short
note at the end." The Album read used to serve a clip and nothing else, so a
moment arrived with no account of how it got there. This module assembles
that account from the records that already exist — it writes nothing, and it
invents nothing.

WHAT IT MAY SAY, AND WHY EACH LANE IS SAFE
------------------------------------------
* ``origin``       — the Take and Slide the clip came from. Position, not
                     judgement.
* ``owner_answer`` — the owner's own five-state self-report on this exact
                     clip, read back to the person who gave it. Never another
                     rater's answer.
* ``coach_agreed`` — that a professional coach heard the same thing, on a
                     PUBLISHED review only. Album membership already requires
                     this leg, so the row reveals nothing the moment's
                     existence did not (BLIND COACH holds by construction);
                     an unpublished judgment never reaches this function. The
                     coach is never named: the student sees "Your coach", and
                     no pseudonym, id or handle crosses the boundary.
* ``exercise``     — the exercise assigned to this exact clip, its explanation
                     video and the attempts the owner recorded against it,
                     with the one they kept.
* ``note``         — what the owner wrote to themselves.

AC-9 holds across every lane: no score, ratio, confidence value, classifier
output or verdict appears in any event. The machine leg is deliberately NOT
an event — the album's own entry rule already required it, and drawing it as
a row on the student's timeline is the closest thing here to surfacing a
model's read as a badge.

Ordering is chronological, because the question the surface answers is "where
did this come from"; an event with no usable timestamp sorts by its lane's
position in the moment's life rather than being dropped.

Best-effort throughout: a lane whose records are missing or unreadable
contributes nothing and never raises into the request path (LIVE LOOP).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The one name the student sees for the person who reviewed them. Coaches are
# never identified to students, so this is a role, not a handle.
COACH_DISPLAY = "Your coach"

# Fallback sort weights for events whose source row carries no timestamp.
# They mirror the order the events can physically happen in.
_LANE_ORDER = {
    "owner_answer": 0,
    "coach_agreed": 1,
    "exercise": 2,
    "note": 3,
}

PRACTICE_PREFIX = "practice:"


def split_moment_key(moment_key: Any) -> tuple[str, str]:
    """('snippet', id) or ('practice_attempt', id) for one Album moment.

    The read surface serves an admitted practice attempt as
    ``practice:<attempt_id>``; everything else is a snippet id.
    """
    raw = str(moment_key or "").strip()
    if raw.startswith(PRACTICE_PREFIX):
        return "practice_attempt", raw[len(PRACTICE_PREFIX):]
    return "snippet", raw


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _owner_answer_event(database: Any, snippet_id: str) -> Optional[dict]:
    """The owner's latest Confident Voice self-report on this exact clip.

    Only the ``confident_voice`` family answers the confidence question; the
    rewrite and praise families use different schemas and different words, so
    mixing them here would put a rater's answer under the wrong question.
    """
    try:
        rows = database.list_take_feedback_self_reports_by_snippet(
            snippet_id) or []
    except Exception:
        return None
    latest = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("feedback_family") != "confident_voice":
            continue
        latest = row
    if not latest:
        return None
    return {
        "kind": "owner_answer",
        "who": "You",
        "at": latest.get("created_at"),
        "response": _text(latest.get("response")),
    }


def _coach_agreed_event(
    database: Any, snippet_id: str, *, published_at: Any = None,
) -> Optional[dict]:
    """A professional coach heard the same thing.

    The publish gate is the caller's: this function is only reached for a
    moment already in the Album, which requires a published professional Yes.
    It re-checks the label anyway so a withdrawn judgment stops being narrated
    even before the next reconciliation removes the entry.
    """
    try:
        from services.professional_confidence import latest_professional_value
        labels = database.get_confidence_labels_by_snippet_ids(
            [snippet_id]) or {}
    except Exception:
        return None
    rows = labels.get(snippet_id)
    try:
        if latest_professional_value(rows) != "yes":
            return None
    except Exception:
        return None
    at = published_at
    if not at and isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("created_at"):
                at = row.get("created_at")
    return {"kind": "coach_agreed", "who": COACH_DISPLAY, "at": at}


def _attempt_view(attempt: Any, *, selected_id: str, resolve_audio) -> Optional[dict]:
    if not isinstance(attempt, dict) or not attempt.get("id"):
        return None
    attempt_id = str(attempt["id"])
    return {
        "attempt_id": attempt_id,
        "index": _int_or_none(attempt.get("attempt_index")),
        "audio_url": resolve_audio(attempt.get("audio_ref")),
        "duration_ms": _int_or_none(attempt.get("duration_ms")),
        "kept": attempt_id == selected_id,
    }


def _exercise_event(
    database: Any, practice: Any, *, resolve_audio,
) -> Optional[dict]:
    """The exercise assigned to this clip, its video, and the attempts.

    The video URL comes from the exercise SNAPSHOT frozen onto the practice
    row, not from the live exercise: the student must be able to watch the
    version they were actually given, even after the catalogue moves on
    (contract §35d — "the user is shown which exact exercise version was
    assigned").
    """
    if not isinstance(practice, dict) or not practice.get("id"):
        return None
    snapshot = practice.get("exercise_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    title = _text(snapshot.get("title"))
    instruction = _text(snapshot.get("instruction"))
    if not title and not instruction:
        return None
    selected_id = _text(practice.get("selected_attempt_id"))
    try:
        rows = database.list_confident_voice_practice_attempts(
            str(practice["id"])) or []
    except Exception:
        rows = []
    attempts = []
    for row in rows:
        view = _attempt_view(row, selected_id=selected_id,
                             resolve_audio=resolve_audio)
        if view:
            attempts.append(view)
    return {
        "kind": "exercise",
        "at": practice.get("created_at"),
        "title": title,
        "instruction": instruction,
        "video_url": _text(snapshot.get("explanation_video_url")) or None,
        "exercise_id": _text(practice.get("exercise_id")) or None,
        "exercise_version": _int_or_none(practice.get("exercise_version")),
        "attempts": attempts,
    }


def _note_events(database: Any, arc_id: str, moment_key: str,
                 owner_user_id: str) -> list:
    try:
        rows = database.list_voice_album_notes(
            arc_id=arc_id, moment_key=moment_key,
            owner_user_id=owner_user_id) or []
    except Exception:
        return []
    out = []
    for row in rows:
        body = _text(row.get("body")) if isinstance(row, dict) else ""
        if not body:
            continue
        out.append({
            "kind": "note",
            "who": "You",
            "at": row.get("created_at"),
            "body": body,
            "note_id": _text(row.get("id")) or None,
        })
    return out


def order_events(events: Any) -> list:
    """Chronological, with a stable per-lane fallback for undated rows.

    An undated event sorts last within its timestamp bucket rather than first,
    because a row with no time is the one we know least about — putting it at
    the head would rewrite the story around it.
    """
    usable = [e for e in (events or []) if isinstance(e, dict)]
    return [
        event for _, event in sorted(
            enumerate(usable),
            key=lambda pair: (
                _text(pair[1].get("at")) or "￿",
                _LANE_ORDER.get(str(pair[1].get("kind") or ""), 9),
                pair[0],
            ),
        )
    ]


def build_moment_history(
    *,
    arc_id: Any,
    moment_key: Any,
    owner_user_id: Any,
    entry: Any = None,
    take_index: Any = None,
    database=None,
    resolve_audio=None,
) -> dict:
    """Assemble one moment's history. Never raises; lanes drop out silently.

    ``entry`` is the Album row the read surface already holds (it carries the
    slide and the Take session), so the caller does not pay for a second read
    of the table it just listed.
    """
    if database is None:
        from services.db import db as database
    if resolve_audio is None:
        def resolve_audio(_ref):
            return None

    arc = _text(arc_id)
    key = _text(moment_key)
    owner = _text(owner_user_id)
    entry = entry if isinstance(entry, dict) else {}
    kind, target = split_moment_key(key)

    origin = {
        "take_index": _int_or_none(take_index),
        "slide_index": _int_or_none(entry.get("slide_index")),
        "at": entry.get("entered_at"),
        "source": kind,
    }

    events: list = []
    if not arc or not target:
        return {"arc_id": arc, "moment_key": key, "origin": origin,
                "events": []}

    try:
        take_session_id = _text(entry.get("take_session_id"))
        practice = None
        snippet_id = target

        if kind == "practice_attempt":
            # An admitted practice attempt inherits the clip it was recorded
            # against: its history is the ORIGINAL moment's history plus the
            # practice itself, which is what "where did this come from" means
            # for an attempt.
            attempt = database.get_confident_voice_practice_attempt(target)
            if isinstance(attempt, dict):
                practice = database.get_confident_voice_practice(
                    _text(attempt.get("practice_id")))
                if isinstance(practice, dict):
                    snippet_id = _text(practice.get("snippet_id")) or target
                    origin["slide_index"] = (
                        origin["slide_index"]
                        if origin["slide_index"] is not None
                        else _int_or_none(practice.get("slide_index"))
                    )
        elif take_session_id:
            candidate = database.get_confident_voice_practice_by_take(
                take_session_id, owner or None)
            if (isinstance(candidate, dict)
                    and _text(candidate.get("snippet_id")) == snippet_id):
                practice = candidate

        owner_event = _owner_answer_event(database, snippet_id)
        if owner_event:
            events.append(owner_event)

        coach_event = _coach_agreed_event(
            database, snippet_id, published_at=entry.get("published_at"))
        if coach_event:
            events.append(coach_event)

        exercise_event = _exercise_event(
            database, practice, resolve_audio=resolve_audio)
        if exercise_event:
            events.append(exercise_event)

        events.extend(_note_events(database, arc, key, owner))
    except Exception as error:
        logger.warning(
            "voice_album_history: assembly failed arc=%s moment=%s: %s",
            arc_id, moment_key, error)

    return {
        "arc_id": arc,
        "moment_key": key,
        "origin": origin,
        "events": order_events(events),
    }
