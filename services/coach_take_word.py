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


def _clean(body: Any) -> tuple[Optional[str], Optional[str], bool, bool]:
    """(text, video_ref, keep_video, share). A body that names no video_ref
    keeps the word's saved video (founder 2026-10-19: a coach who edits only
    the words no longer loses their video); an explicit null or empty
    video_ref removes it."""
    fields = body if isinstance(body, dict) else {}
    text = " ".join(str(fields.get("text") or "").split()) or None
    if text and len(text) > MAX_TEXT:
        raise TakeWordRefusal(f"Keep the message under {MAX_TEXT} characters.")
    video_ref = str(fields.get("video_ref") or "").strip() or None
    if not text and not video_ref:
        raise TakeWordRefusal("Write a message or add a video.")
    return text, video_ref, "video_ref" not in fields, fields.get("share") is True


def _stored_ref(video_ref: Optional[str], take_session_id: str) -> Optional[str]:
    """The ref the row keeps for the coach's video (N79, 2026-10-19).

    The upload hands the coach a signed link (``store_session_video``), and
    the panel sends that link back on save. Kept as it was, it expired and
    was never transcribed, so no Take-word video was ever turned into words.
    This Take's own upload is kept as the ``s3://bucket/key`` marker the
    upload wrote (reads sign it fresh); anything else is kept as sent."""
    from services.coach_word_pairs import take_video_object
    found = take_video_object(video_ref, take_session_id)
    return f"s3://{found[0]}/{found[1]}" if found else video_ref


def save_take_word(database: Any, *, take_session_id: str, coach_id: str,
                   body: Any) -> dict:
    """PUT: the coach's one word for this Take, replaced on its row on each
    save (the database keeps every earlier version, 0480); `share: true`
    sends it. Raises TakeWordRefusal for anything the coach can fix.
    Returns the payload the coach reads back."""
    text, video_ref, keep_video, share = _clean(body)
    video_ref = _stored_ref(video_ref, str(take_session_id))
    row = database.upsert_coach_take_word(
        take_session_id=str(take_session_id), coach_id=str(coach_id),
        text=text, video_ref=video_ref, share=share, keep_video=keep_video)
    if not isinstance(row, dict):
        raise TakeWordRefusal("Could not save the word.", "V2_ERROR", 500)
    # What the coach saw when they saved it (0482, N79): the whole Take, their
    # diagnoses and its Ideal Text; never on their own Take; capture only,
    # off the request.
    from services.coach_answer_situation import freeze_take_word_in_background
    freeze_take_word_in_background(database, word_row=row, coach_id=str(coach_id))
    if share:
        _tell_the_speaker(database, str(take_session_id), text=text,
                          video_ref=row.get("video_ref") or None,
                          first_share=_first_share(row))
        # The Take's closing summary is rewritten with the word, in place
        # (founder lock 2026-10-12, section 3). Behind the save.
        from services.take_summary import coach_update
        coach_update(database, str(take_session_id), text)
    _the_pair(database, row, coach_id=str(coach_id), text=text, new_video=not keep_video)
    return take_word_payload(row) or {}


def _the_pair(database: Any, row: dict, *, coach_id: str, text: Optional[str],
              new_video: bool = True) -> None:
    """7 (C5-a, 0411): when a draft was shown and the coach's words differ,
    the (draft, final) pair; a video's transcript is a second final. The
    draft the row carries is settled in coach_draft_history (0481): whether
    the saved words are that draft as written. All best-effort; the word is
    saved either way."""
    try:
        from services.coach_draft_history import settle
        from services.coach_word_pairs import (
            record_take_word_pair, transcribe_take_word_video_in_background,
        )
        settle(database, row, final=text)
        record_take_word_pair(database, word_row=row, coach_id=coach_id, final_text=text)
        if not row.get("transcript") and (new_video or not row.get("video_ref")):
            # No video, or a new one not yet transcribed (the save cleared the
            # old words): no video's words teach (0479). A kept video is left
            # alone: its words may be landing right now, and no one sends it
            # to the transcriber again.
            record_take_word_pair(database, word_row=row, coach_id=coach_id,
                                  final_text=None, final_kind="transcript")
        # Only a save that brings a video sends it to the transcriber: a
        # word-only edit never sends the kept video again (one still being
        # transcribed, or one with no speech in it).
        if new_video and row.get("video_ref") and not row.get("transcript"):
            transcribe_take_word_video_in_background(database, word_row=row,
                                                     coach_id=coach_id)
    except Exception as e:  # noqa: BLE001 -- the word is saved either way
        _log.info("take word pair skipped take=%s: %s", row.get("take_session_id"), e)


def _first_share(row: dict) -> bool:
    """This save stamped shared_at (the upsert stamps it once, with the same
    time as updated_at); a later edit of a shared word keeps the old stamp."""
    shared_at = row.get("shared_at")
    return bool(shared_at) and shared_at == row.get("updated_at")


def _tell_the_speaker(database: Any, take_session_id: str, *,
                      text: Optional[str], video_ref: Optional[str],
                      first_share: bool = False) -> None:
    """The project's Ideal Text bubble comes back to the bottom of the chat,
    as a publish did (founder 2026-09-25, Q39 B); after the Take's review, the
    word is its own coach update bubble (lock 2026-10-12, section 3). On the
    first share the speaker also gets one WhatsApp message if they left a
    number (founder 2026-10-12) and the coach-feedback email (2026-10-14).
    Best-effort."""
    try:
        from services.arc_notifications import bump_ideal_bubble
        session = database.v2_get_session_by_id(take_session_id) or {}
        if session.get("user_id") and session.get("arc_id"):
            bump_ideal_bubble(database, session["user_id"], session["arc_id"])
        if not first_share:
            _log.info("whatsapp: take=%s was shared before, no message", take_session_id)
        elif session.get("user_id"):
            from services.coach_feedback_email import send_coach_feedback_email_in_background
            from services.whatsapp_notify import notify_coach_feedback_in_background
            notify_coach_feedback_in_background(database, session["user_id"], take_session_id)
            send_coach_feedback_email_in_background(
                database, take_session_id=take_session_id, moments=0)
    except Exception as e:  # noqa: BLE001 -- the word is saved either way
        _log.info("take word bubble bump skipped take=%s: %s", take_session_id, e)
    try:
        from services.take_summary import coach_update_message
        coach_update_message(database, take_session_id=take_session_id,
                             text=text, video_ref=video_ref)
    except Exception as e:  # noqa: BLE001 -- the word is saved either way
        _log.info("coach update bubble skipped take=%s: %s", take_session_id, e)


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
    """GET: this coach's own word for the Take, or None when there is none.
    A failed read RAISES (N80): answered as "no word", the panel would
    draft over the saved words."""
    return take_word_payload(database.read_coach_take_word(str(take_session_id), str(coach_id)))


def latest_shared_word(database: Any, sessions: Any) -> Optional[dict]:
    """The most recently shared word across these spoken takes, as
    {text, video_url, take_index, published_at, take_session_id,
    changed_at}, or None. Best-effort. ``changed_at`` (when that Take's
    shared words last changed, N80) is for the "new" check only: the
    journey takes it out before the payload leaves.

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
    from services.coach_feedback_signal import word_changed_at
    served = str(latest.get("take_session_id"))
    return {
        "text": payload.get("text"),
        "video_url": payload.get("video_url"),
        "take_index": take.get("take_index"),
        "published_at": latest.get("shared_at"),
        "take_session_id": str(take.get("id") or "") or None,
        "changed_at": word_changed_at(
            w for w in shared if str(w.get("take_session_id")) == served),
    }
