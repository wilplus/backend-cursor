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
    practice, behind the same gates as the practice page."""
    wanted: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        clip = meta.get("clip") if isinstance(meta, dict) else None
        if isinstance(clip, dict) and clip.get("practice_id") and clip.get("attempt_id"):
            wanted.setdefault(str(clip["practice_id"]), []).append(clip)
    if not wanted:
        return
    try:
        if not _practice_allowed(user_id, database):
            return
    except Exception:
        logger.warning("lounge clips: practice gates unreadable", exc_info=True)
        return
    for pid, clips in wanted.items():
        try:
            if not database.get_confident_voice_practice(pid, str(user_id)):
                continue
            rows = {str(r.get("id")): r
                    for r in database.list_confident_voice_practice_attempts(pid) or []}
        except Exception:
            logger.warning("lounge clips: practice %s unreadable", pid,
                           exc_info=True)
            continue
        for clip in clips:
            row = rows.get(str(clip["attempt_id"]))
            url = resolve(row.get("audio_ref")) if row else None
            if url:
                clip["src"] = url


def attach_card_decks(messages: list, user_id: str, database: Any) -> None:
    """The Ideal Text card at a review's end shows its project's first
    slide: each card gets `metadata.deck.presentation_ref`, a fresh link to
    the reader's own project's deck (null for a deckless project, whose
    card shows the default deck). Unowned or unreadable: no `deck`."""
    from services.coach_video_storage import refreshed_media_url
    from services.ideal_text_read import _deck_identity
    from services.project_ownership import session_actor_id

    decks: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        if not isinstance(meta, dict) or meta.get("step") != "end":
            continue
        arc = str(meta.get("arc_id") or "")
        if not arc:
            continue
        if arc not in decks:
            try:
                sessions = database.takes.get_arc_sessions(arc) or []
                owned = any(session_actor_id(s) == str(user_id) for s in sessions)
                ref = _deck_identity(sessions)[0] if owned else None
                decks[arc] = {"presentation_ref": refreshed_media_url(ref) if ref else None} if owned else None
            except Exception:
                logger.warning("lounge cards: deck unreadable for %s", arc, exc_info=True)
                decks[arc] = None
        if decks[arc] is not None:
            meta["deck"] = decks[arc]
