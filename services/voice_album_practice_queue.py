"""The "Practice new" queue — clips still waiting for the owner's answer.

Founder 2026-09-18: the Album's second half. "Practice yours" is the moments
that already made it in; "Practice new" is every clip of yours the machine
starred that you have not answered yet, one per screen.

WHY EVERY STARRED CLIP AND NOT ONLY THE CARDS YOU WERE SHOWN
------------------------------------------------------------
A Manager-exposed Confident Voice CARD only exists once the Take's review has
been opened, so a queue built from cards would hold only the cards a user was
shown and skipped — usually a handful, often none. Minting cards outside the
review to fill it would change what counts as exposed for the Manager's
budget (L2), so this queue is built from the machine's STARS instead, and the
answer is stored as owner routing on the clip rather than as a response to a
card that does not exist. Nothing here touches the Manager.

PROVENANCE (L3)
---------------
An answer given here is an owner self-report about the owner's own recording.
It lands in `owner_voice_album_routing`, which no training, quorum,
calibration, evaluation, SFT or DPO reader consumes. It is never a blind peer
label and never a coach judgment.

Only `yes` satisfies the Voice Album's USER leg, and only alongside the
machine and coach legs — so answering here can help a moment in, but can
never put one in on its own.

THE GENERAL-DATABASE LANE IS NOT SERVED.
Clips a coach uploaded to the shared corpus for blind rating are a Phase-2
corpus path, and Phase-2 corpus/dataset/training/evaluation stays disabled
until separately authorized. The lane reports itself unavailable rather than
quietly returning an empty list that reads like "you are done".

AC-9: the queue carries playback and position. No score, no machine read, no
verdict — the star is what selected the clip, never something the user sees.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_STAR_KIND = "emphasize"
_STAR_TRIGGER = "confident"


def _starred_snippet_ids(database: Any, arc_id: str) -> set:
    """Clips the star lane marked confident for this project.

    A neutral confidence-review nomination is not a star, the same rule the
    Album's own machine leg applies — the two must not drift apart.
    """
    try:
        rows = database.get_moment_suggestions_by_arc(str(arc_id)) or {}
    except Exception:
        return set()
    return {
        str(snippet_id) for snippet_id, row in rows.items()
        if isinstance(row, dict)
        and row.get("kind") == _STAR_KIND
        and row.get("trigger") == _STAR_TRIGGER
        and snippet_id
    }


def _answered_snippet_ids(database: Any, arc_id: str) -> set:
    """Clips the owner has already answered, from BOTH places an answer lands.

    Answering inside a Take review writes a self-report; answering here writes
    routing. A queue that read only one of them would re-ask a question the
    user has already answered on the other surface.

    ANY answer removes a clip, not just a yes: the five states are answers,
    and re-asking someone who said "no" until they say "yes" is not a queue,
    it is nagging.
    """
    answered = set()
    for reader, label in (
        (database.list_confident_voice_self_reports, "self-report"),
        (database.list_owner_voice_album_routes, "routing"),
    ):
        try:
            for row in (reader(str(arc_id)) or []):
                if isinstance(row, dict) and row.get("snippet_id"):
                    answered.add(str(row["snippet_id"]))
        except Exception as error:
            logger.warning("practice queue: %s read failed arc=%s: %s",
                           label, arc_id, error)
    return answered


def _is_countable_take(session: Any) -> bool:
    """A spoken Take whose analysis finished.

    Reads are paired variants of their spoken take and are not Takes of their
    own; a Take still processing has no snippets worth queueing yet.
    """
    return bool(
        isinstance(session, dict)
        and session.get("recording_kind") != "read"
        and not session.get("paired_session_id")
        and session.get("analysis_state") in (None, "ready")
    )


def build_practice_queue(
    *,
    sessions_by_arc: Any,
    titles_by_arc: Any = None,
    database=None,
    resolve_audio=None,
) -> list:
    """Every starred, unanswered clip the owner still has to answer.

    Ordered project by project (oldest project first), then Take, then slide —
    so a backlog is worked through in the order it accumulated rather than
    jumping between projects.

    Best-effort: a project whose reads fail contributes nothing and never
    raises into the request path (LIVE LOOP).
    """
    if database is None:
        from services.db import db as database
    if resolve_audio is None:
        def resolve_audio(_snippet):
            return None
    titles = titles_by_arc if isinstance(titles_by_arc, dict) else {}

    out: list = []
    for arc_id, sessions in (sessions_by_arc or {}).items():
        arc = str(arc_id)
        pending = _starred_snippet_ids(database, arc) - _answered_snippet_ids(
            database, arc)
        if not pending:
            continue
        for session in sorted(
            [s for s in (sessions or []) if _is_countable_take(s)],
            key=lambda s: (s.get("take_index") or 0),
        ):
            session_id = str(session.get("id") or "")
            if not session_id:
                continue
            try:
                snippets = database.get_snippets_by_session(session_id) or []
            except Exception as error:
                logger.warning("practice queue: snippet read failed "
                               "session=%s: %s", session_id, error)
                continue
            rows = []
            for snippet in snippets:
                if not isinstance(snippet, dict):
                    continue
                snippet_id = str(snippet.get("id") or "")
                if snippet_id not in pending:
                    continue
                slide = snippet.get("slide_index")
                rows.append({
                    "snippet_id": snippet_id,
                    "arc_id": arc,
                    "arc_title": titles.get(arc),
                    "take_session_id": session_id,
                    "take_index": session.get("take_index"),
                    "slide_index": (slide if isinstance(slide, int)
                                    and not isinstance(slide, bool) else None),
                    "audio_url": resolve_audio(snippet),
                    "start_offset_ms": snippet.get("start_offset_ms"),
                    "duration_ms": snippet.get("duration_ms"),
                })
            rows.sort(key=lambda row: (row["slide_index"] is None,
                                       row["slide_index"] or 0))
            out.extend(rows)
    return out


def record_practice_answer(
    *,
    arc_id: Any,
    take_session_id: Any,
    snippet_id: Any,
    response: Any,
    owner_user_id: Any,
    database=None,
) -> tuple[bool, Optional[str]]:
    """Store one five-state answer on one exact clip.

    Returns ``(saved, error_code)``. ``error_code`` is ``"clip_not_found"``
    when the clip does not belong to the Take the caller named — an answer is
    about one recording, and a snippet id from elsewhere would attach it to
    the wrong one — or ``"write_failed"`` when the row would not persist.

    The reconciliation afterwards can admit a newly aligned moment, but only
    where the machine and coach legs already agree; a `yes` here can never put
    a moment in the Album on its own (L3). It is best-effort and never fails
    the answer the user already gave (LIVE LOOP).
    """
    if database is None:
        from services.db import db as database

    snippets = database.get_snippets_by_session(str(take_session_id)) or []
    snippet = next(
        (s for s in snippets
         if isinstance(s, dict) and str(s.get("id")) == str(snippet_id)),
        None,
    )
    if snippet is None:
        return False, "clip_not_found"

    slide = snippet.get("slide_index")
    saved = database.upsert_owner_voice_album_route(
        snippet_id=str(snippet_id),
        owner_user_id=str(owner_user_id),
        arc_id=str(arc_id),
        response=str(response),
        slide_index=(slide if isinstance(slide, int)
                     and not isinstance(slide, bool) else None),
    )
    if not saved:
        return False, "write_failed"

    try:
        from services.voice_album import refresh_voice_album
        refresh_voice_album(str(arc_id), database=database)
    except Exception as error:
        logger.warning("practice answer: album refresh failed arc=%s: %s",
                       arc_id, error)
    return True, None
