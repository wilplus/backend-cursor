"""Fresh links for the speaker's clips in the Lounge (founder lock
2026-10-12, moment and feedback chat): a walk step stores the moment's
signed link, which dies after six hours. On every read the link is
signed again from the moment's own recording, but only for a recording
that belongs to the reader. Best-effort: anything unreadable keeps the
stored link, and the player shows its existing "unavailable".
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class _SessionSnippets:
    """The database, with ``get_snippets_by_session`` served from one batch
    read of every Take on the page (light columns only). Anything else, and
    any session the batch could not read, goes to the database as before."""

    def __init__(self, database: Any, rows_by_session: dict):
        self._database = database
        self._rows = rows_by_session

    def get_snippets_by_session(self, session_id: str, **kwargs: Any) -> list:
        rows = self._rows.get(str(session_id))
        if rows is None or kwargs:
            return self._database.get_snippets_by_session(session_id, **kwargs)
        return rows

    def __getattr__(self, name: str) -> Any:
        return getattr(self._database, name)


def with_page_snippets(messages: list, database: Any) -> Any:
    """Read the recordings of every Take on this page in one go (founder
    2026-10-14: the Lounge took seven seconds reading each Take's pieces
    with their word timings, once for moment clips and again for the whole
    Take). Falls back to the plain database when the batch read fails."""
    sids: set = set()
    for m in messages or []:
        meta = m.get("metadata")
        if not isinstance(meta, dict):
            continue
        if m.get("kind") == "walk_step" and meta.get("take_session_id"):
            sids.add(str(meta["take_session_id"]))
        elif m.get("kind") == "recording_summary" and meta.get("session_id"):
            sids.add(str(meta["session_id"]))
    reader = getattr(database, "get_snippet_audio_rows_by_sessions", None)
    if not sids or not callable(reader):
        return database
    rows = reader(sorted(sids))
    return _SessionSnippets(database, rows) if isinstance(rows, dict) else database


def refresh_walk_clips(messages: list, user_id: str, database: Any,
                       resolve: Callable[[dict], Optional[str]]) -> None:
    """Re-sign `metadata.clip.src` in place on the reader's walk steps."""
    wanted: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        clip = meta.get("clip") if isinstance(meta, dict) else None
        sid = meta.get("take_session_id") if isinstance(meta, dict) else None
        if isinstance(clip, dict) and clip.get("snippet_id") and sid:
            wanted.setdefault(str(sid), []).append(clip)
    for sid, clips in wanted.items():
        try:
            rows = {str(r.get("id")): r
                    for r in database.get_snippets_by_session(sid) or []
                    if str(r.get("user_id") or "") == str(user_id)}
        except Exception:
            logger.warning("lounge clips: snippets unreadable for %s", sid,
                           exc_info=True)
            continue
        for clip in clips:
            row = rows.get(str(clip["snippet_id"]))
            try:
                url = resolve(row) if row else None
            except Exception:
                logger.warning("lounge clips: could not sign %s",
                               clip["snippet_id"], exc_info=True)
                url = None
            if url and row:
                clip["src"] = url
                clip["start_ms"] = row.get("start_offset_ms")
                clip["duration_ms"] = row.get("duration_ms")


def _practice_allowed(user_id: str, database: Any) -> bool:
    """The practice page's own gates: the purpose is on, and this person's
    "Personalised practice" choice says yes (routes/phase2_guard.py)."""
    from services.processing_authorization import (
        ProcessingAuthorizationService,
    )
    from services.processing_purposes import purpose_is_operational

    if not purpose_is_operational("personalized_exercise_recommendation"):
        return False
    service = ProcessingAuthorizationService(database)
    principal = service.user_acquisition_principal(str(user_id))
    if not principal:
        return not service.enforced
    return bool(service.choice_permitted(principal, "personalised_practice"))


def refresh_practice_clips(messages: list, user_id: str, database: Any,
                           resolve: Callable[[Any], Optional[str]]) -> None:
    """Re-sign a practise try's clip in place, from the reader's own
    practice, behind the same gates as the practice page. The gates (three
    reads) and the practice reads run side by side; a clip is signed only
    once the gates said yes."""
    from services.parallel import run_in_parallel

    wanted: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        clip = meta.get("clip") if isinstance(meta, dict) else None
        if isinstance(clip, dict) and clip.get("practice_id") and clip.get("attempt_id"):
            wanted.setdefault(str(clip["practice_id"]), []).append(clip)
    if not wanted:
        return

    def gate() -> bool:
        try:
            return bool(_practice_allowed(user_id, database))
        except Exception:
            logger.warning("lounge clips: practice gates unreadable", exc_info=True)
            return False

    def attempts(pid: str) -> dict:
        try:
            if not database.get_confident_voice_practice(pid, str(user_id)):
                return {}
            return {str(r.get("id")): r
                    for r in database.list_confident_voice_practice_attempts(pid) or []}
        except Exception:
            logger.warning("lounge clips: practice %s unreadable", pid,
                           exc_info=True)
            return {}

    def reads() -> dict:
        return {pid: attempts(pid) for pid in wanted}

    allowed, rows_by_practice = run_in_parallel(gate, reads)
    if not allowed:
        return
    for pid, clips in wanted.items():
        rows = rows_by_practice.get(pid) or {}
        for clip in clips:
            row = rows.get(str(clip["attempt_id"]))
            url = resolve(row.get("audio_ref")) if row else None
            if url:
                clip["src"] = url


def _arc_sessions_by_id(arcs: list, database: Any) -> dict:
    """{arc_id: takes} for the page's projects: one batch read when the
    repository offers it, else one read per project as before."""
    reader = getattr(getattr(database, "takes", None), "get_arc_sessions_many", None)
    if callable(reader):
        try:
            rows = reader(arcs)
        except Exception:
            logger.warning("lounge cards: batch deck read failed", exc_info=True)
            rows = None
        if isinstance(rows, dict):
            return rows
    return {arc: database.takes.get_arc_sessions(arc) or [] for arc in arcs}


def attach_card_decks(messages: list, user_id: str, database: Any) -> None:
    """The Ideal Text card (a review's end, or a Take's Ideal Text bubble)
    shows its project's first slide: each card gets `metadata.deck.presentation_ref`, a fresh link to
    the reader's own project's deck (null for a deckless project, whose
    card shows the default deck). Unowned or unreadable: no `deck`. Every
    project on the page is read in one go (founder 2026-10-18: one read per
    project, one after another)."""
    from services.coach_video_storage import refreshed_media_url
    from services.ideal_text_read import _deck_identity
    from services.project_ownership import session_actor_id

    cards: dict = {}
    for m in messages or []:
        # A review's card, or a Take's Ideal Text bubble drawn as the same
        # small card (founder 2026-10-14, one card per Take).
        meta = m.get("metadata") if m.get("kind") in ("walk_step", "ideal_text") else None
        if not isinstance(meta, dict):
            continue
        if m.get("kind") == "walk_step" and meta.get("step") != "end":
            continue
        arc = str(meta.get("arc_id") or "")
        if arc:
            cards.setdefault(arc, []).append(meta)
    if not cards:
        return
    try:
        by_arc = _arc_sessions_by_id(sorted(cards), database)
    except Exception:
        logger.warning("lounge cards: decks unreadable", exc_info=True)
        return
    for arc, metas in cards.items():
        try:
            sessions = by_arc.get(arc) or []
            owned = any(session_actor_id(s) == str(user_id) for s in sessions)
            if not owned:
                continue
            ref = _deck_identity(sessions)[0]
            deck = {"presentation_ref": refreshed_media_url(ref) if ref else None}
        except Exception:
            logger.warning("lounge cards: deck unreadable for %s", arc, exc_info=True)
            continue
        for meta in metas:
            meta["deck"] = deck


def attach_take_audio(messages: list, user_id: str, database: Any,
                      resolve: Callable[[Any], Optional[str]]) -> None:
    """The "Your Recording" bubble plays the whole Take, as a moment's clip
    plays its part: each gets `metadata.audio.src`, a fresh link to the
    reader's own recording. Unowned or unreadable: no `audio`."""
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "recording_summary" else None
        sid = meta.get("session_id") if isinstance(meta, dict) else None
        if not sid:
            continue
        try:
            rows = [r for r in database.get_snippets_by_session(str(sid)) or []
                    if str(r.get("user_id") or "") == str(user_id)
                    and r.get("audio_segment_path")]
            url = resolve(rows[0]["audio_segment_path"]) if rows else None
        except Exception:
            logger.warning("lounge takes: audio unreadable for %s", sid,
                           exc_info=True)
            url = None
        if url and isinstance(meta, dict):
            meta["audio"] = {"src": url}


def enrich_page(page: dict, user_id: str, database: Any, *,
                resolve_snippet: Callable[[dict], Optional[str]],
                resolve_ref: Callable[[Any], Optional[str]],
                with_flags: bool) -> None:
    """Everything the Lounge read adds to a page of messages: fresh clip,
    practice, deck and recording links, and (newest page only) the Ideal
    Text bubble's "new". The reads are independent, so they run side by
    side (founder 2026-10-18, "optimise the loading time") instead of one
    after another; the slowest one, not their sum, sets the wait.

    Thread safety: each group writes keys no other group touches. Walk
    clips carry a ``snippet_id`` and practise clips a ``practice_id`` (never
    both), decks write ``deck`` on cards, recordings write ``audio`` on
    readouts, and the flags are a return value. Clips and recordings share
    one read of the page's Takes, so they stay in one group, in order.
    """
    from services.parallel import run_in_parallel
    from services.request_context import lap

    messages = page.get("messages") or []

    def recordings() -> None:
        with lap("takes"):
            clips_db = with_page_snippets(messages, database)
        with lap("clips"):
            refresh_walk_clips(messages, user_id, clips_db, resolve_snippet)
        with lap("audio"):
            attach_take_audio(messages, user_id, clips_db, resolve_ref)

    def practice() -> None:
        with lap("practice"):
            refresh_practice_clips(messages, user_id, database, resolve_ref)

    def decks() -> None:
        with lap("decks"):
            attach_card_decks(messages, user_id, database)

    def flags() -> Optional[dict]:
        if not with_flags:
            return None
        # The Ideal Text bubble's "new" (D-FW-5, walk lock flow 1): one
        # yes/no per project, never a count; {} when it cannot be read.
        from services.coach_feedback_signal import lounge_flags
        with lap("flags"):
            return lounge_flags(database, user_id)

    _, _, _, fresh = run_in_parallel(recordings, practice, decks, flags)
    if fresh is not None:
        page["new_coach_feedback"] = fresh
