"""A word for this Take (founder 2026-09-30, B3; build plan P2-5).

One optional message and one optional video per Take, per coach. The coach
writes it after the last moment of a Take, or not at all; sharing sends it
to the speaker, who reads it as "Your coach" on that Take's Ideal Text
(the sheet that exists, Final Screens L8). A word belongs to its Take
(founder 2026-10-05, N48.3 Q11 A): the page showing Take 3 never serves the
word left on Take 2.

It replaces the arc-level publish as the speaker's coach message: where a
Take has a shared word, that is what the speaker reads; where it has none,
the published revision still serves until the removals retire it (P2-19).
Nothing here gates a per-moment share (LIVE LOOP), and nothing here is a
score (AC-9).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

MAX_TEXT = 4000


class TakeWordRefusal(Exception):
    def __init__(self, message: str, code: str = "INVALID_INPUT", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _clean(body: Any) -> tuple[Optional[str], Optional[str], bool]:
    fields = body if isinstance(body, dict) else {}
    text = " ".join(str(fields.get("text") or "").split()) or None
    if text and len(text) > MAX_TEXT:
        raise TakeWordRefusal(f"Keep the message under {MAX_TEXT} characters.")
    video_ref = str(fields.get("video_ref") or "").strip() or None
    if not text and not video_ref:
        raise TakeWordRefusal("Write a message or add a video.")
    return text, video_ref, fields.get("share") is True


def save_take_word(database: Any, *, take_session_id: str, coach_id: str,
                   body: Any) -> dict:
    """PUT: the coach's one word for this Take, replaced on each save;
    `share: true` sends it. Raises TakeWordRefusal for anything the coach
    can fix. Returns the payload the coach reads back."""
    text, video_ref, share = _clean(body)
    row = database.upsert_coach_take_word(
        take_session_id=str(take_session_id), coach_id=str(coach_id),
        text=text, video_ref=video_ref, share=share)
    if not isinstance(row, dict):
        raise TakeWordRefusal("Could not save the word.", "V2_ERROR", 500)
    if share:
        _tell_the_speaker(database, str(take_session_id))
    _the_pair(database, row, coach_id=str(coach_id), text=text)
    return take_word_payload(row) or {}


def _the_pair(database: Any, row: dict, *, coach_id: str, text: Optional[str]) -> None:
    """7 (C5-a, 0411): when a draft was shown and the coach's words differ,
    the (draft, final) pair; a video's transcript is a second final. Both
    best-effort and only while the surface is on; the word is saved
    either way."""
    try:
        from services.coach_word_pairs import (
            record_take_word_pair, transcribe_take_word_video, word_pairs_enabled,
        )
        if not word_pairs_enabled():
            return
        record_take_word_pair(database, word_row=row, coach_id=coach_id, final_text=text)
        if row.get("video_ref") and not row.get("transcript"):
            transcribe_take_word_video(database, word_row=row, coach_id=coach_id)
    except Exception as e:  # noqa: BLE001 -- the word is saved either way
        _log.info("take word pair skipped take=%s: %s", row.get("take_session_id"), e)


def _tell_the_speaker(database: Any, take_session_id: str) -> None:
    """The project's Ideal Text bubble comes back to the bottom of the chat,
    as a publish did (founder 2026-09-25, Q39 B). Best-effort."""
    try:
        from services.arc_notifications import bump_ideal_bubble
        session = database.v2_get_session_by_id(take_session_id) or {}
        if session.get("user_id") and session.get("arc_id"):
            bump_ideal_bubble(database, session["user_id"], session["arc_id"])
    except Exception as e:  # noqa: BLE001 -- the word is saved either way
        _log.info("take word bubble bump skipped take=%s: %s", take_session_id, e)


def take_word_payload(row: Any) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    video_ref = row.get("video_ref") or None
    video_url = None
    if video_ref:
        from services.coach_video_storage import refreshed_media_url
        video_url = refreshed_media_url(video_ref)
    return {
        "take_session_id": str(row.get("take_session_id") or ""),
        "text": row.get("text") or None,
        "video_ref": video_ref,
        "video_url": video_url,
        "shared_at": row.get("shared_at"),
        "updated_at": row.get("updated_at"),
    }


def take_word_for(database: Any, *, take_session_id: str, coach_id: str) -> Optional[dict]:
    """GET: this coach's own word for the Take, or None."""
    reader = getattr(database, "get_coach_take_word", None)
    if reader is None:
        return None
    return take_word_payload(reader(str(take_session_id), str(coach_id)))


def latest_shared_word(database: Any, sessions: Any) -> Optional[dict]:
    """The most recently shared word across these spoken takes, as
    {text, video_url, take_index, published_at, take_session_id}, or None.
    Best-effort.

    THE WORD BELONGS TO ITS TAKE (founder 2026-10-05, N48.3 Q11 A; contract
    35g-6). The speaker's read passes only the Take on screen
    (`coach_message_read.coach_message_for`), so another Take's word is
    never served in its place."""
    rows = [s for s in (sessions or []) if isinstance(s, dict) and s.get("id")]
    if not rows:
        return None
    reader = getattr(database, "list_shared_coach_take_words", None)
    if reader is None:
        return None
    try:
        words = reader([str(s["id"]) for s in rows]) or []
    except Exception as e:  # noqa: BLE001 -- the published message still serves
        _log.warning("take words read failed: %s", e, exc_info=True)
        return None
    shared = [w for w in words if isinstance(w, dict) and w.get("shared_at")]
    if not shared:
        return None
    latest = max(shared, key=lambda w: str(w.get("shared_at")))
    take = next((s for s in rows if str(s["id"]) == str(latest.get("take_session_id"))), {})
    payload = take_word_payload(latest) or {}
    if not payload.get("text") and not payload.get("video_url"):
        return None
    return {
        "text": payload.get("text"),
        "video_url": payload.get("video_url"),
        "take_index": take.get("take_index"),
        "published_at": latest.get("shared_at"),
        "take_session_id": str(take.get("id") or "") or None,
    }
