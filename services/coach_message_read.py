"""The coach's overall message for the speaker (founder 2026-09-29, Q1).

The coach writes one overall message when they publish a review, and may
record a video with it. Both were stored and never reached the speaker: the
only screen that showed them (the insight chat bubble) is no longer created.
The Ideal Text now opens its Feedback sheet on them (Final Screens L8), and
this is the one read that serves them.

- OWNER ONLY. The caller has already established that the reader owns the
  project; nothing here is served to a coach or a peer.
- PUBLISHED ONLY. The words come from the Take's published review revision
  (`coach_review_revisions`), never from `v2_sessions.coach_overall_message`,
  which the coach's message step also writes while drafting. Only a Take with
  `results_published_at` counts.
- THE TAKE ON SCREEN ONLY (founder 2026-10-18, decisions log N77; it
  supersedes N48.3 Q11 A's earlier-Take fallback, contract 35g-6). A
  coach's word belongs to the Take it was left on, and the read serves the
  word (or published review) of the Take the Ideal Text shows (its
  `latest_take_session_id`) and nothing else: a later Take starts without
  it. A word a coach leaves on an earlier Take after a newer one exists
  reaches the speaker through its Lounge bubble ("Later · from your
  coach"), the WhatsApp and the email, and stays in the Lounge history.
  Every message names its Take (`take_session_id`, `take_index`). No Take
  on screen, no word.
- QUALITATIVE. Words and a video; no score, no verdict (AC-9).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _latest_published(sessions: Any) -> Optional[dict]:
    published = [
        s for s in (sessions or [])
        if isinstance(s, dict) and s.get("results_published_at")
    ]
    if not published:
        return None
    return max(published, key=lambda s: str(s.get("results_published_at")))


def coach_message_for(database: Any, sessions: Any,
                      take_session_id: Optional[str]) -> Optional[dict]:
    """{text, video_url, take_index, published_at, take_session_id} for the
    Take on screen, else None: never another Take's word (N77).
    Best-effort: a failed read is None, never an error."""
    take = str(take_session_id or "")
    rows = [s for s in (sessions or []) if isinstance(s, dict)]
    shown = [s for s in rows if take and str(s.get("id") or "") == take]
    if not shown:
        return None
    return _message_for_take(database, shown, take)


def _message_for_take(database: Any, shown: list, take: str) -> Optional[dict]:
    """The Take on screen's own message. A WORD FOR THIS TAKE (founder
    2026-09-30, B3; 0403) comes first: where a coach shared one on this
    Take, the latest shared word; this Take's arc-level publish serves only
    where none exists, until the removals retire it (P2-19)."""
    from services.coach_take_word import latest_shared_word
    word = latest_shared_word(database, shown)
    if word is not None:
        return word
    latest = _latest_published(shown)
    if latest is None:
        return None
    try:
        session = database.v2_get_session_by_id(str(latest.get("id"))) or {}
    except Exception as e:
        logger.warning("coach message read failed session=%s: %s",
                       latest.get("id"), e)
        return None
    revision = database.get_coach_review_revision(
        str(session.get("coach_review_revision_id") or "")) or {}
    text = revision.get("overall_message")
    text = text.strip() if isinstance(text, str) else ""
    video_ref = session.get("coach_video_ref") or None
    video_url = None
    if video_ref:
        from services.coach_video_storage import refreshed_media_url
        video_url = refreshed_media_url(video_ref)
    if not text and not video_url:
        return None
    return {
        "text": text or None,
        "video_url": video_url,
        "take_index": latest.get("take_index"),
        "published_at": (revision.get("published_at")
                         or latest.get("results_published_at")),
        "take_session_id": take,
    }


def _word_seen(database: Any, actor_id: str, sessions: Any) -> Optional[dict]:
    """{Take: when the speaker last watched its coach word} for these
    Takes; None when it cannot be read."""
    takes = [str(s["id"]) for s in sessions or [] if isinstance(s, dict) and s.get("id")]
    try:
        return database.list_coach_take_word_seen(str(actor_id), takes) or {}
    except Exception as e:
        logger.warning("coach word seen read failed: %s", e, exc_info=True)
        return None


def journey_payload(database: Any, actor_id: str, arc_id: str,
                    take_count: int, sessions: Any,
                    take_session_id: Optional[str]) -> dict:
    """The Ideal Text enrichment's `journey` section, for the project OWNER
    (the route refuses anyone else before it runs): whether the guided next
    steps were seen, and the coach's overall message and video for the Take
    on screen only (Q1, Final Screens L8; N77).

    The message carries ``unseen`` (founder 2026-10-19, N80): its word
    changed after the speaker last watched it, from any door (the WhatsApp
    or email link, the dot card, the bubble), the dot's own rule. It is
    read for the message's own Take, the Take on screen (N77). When the
    watch cannot be read, the word counts as unseen: one more tap at most,
    never a hidden coach word."""
    from services.coach_feedback_signal import newer_than_seen
    from services.journey_messages import journey_seen
    from services.parallel import run_in_parallel
    # Independent reads, read together (2026-10-18: this section was the
    # slowest one on the Ideal Text open).
    seen, message, watched = run_in_parallel(
        lambda: journey_seen(database, actor_id, arc_id, take_count),
        lambda: coach_message_for(database, sessions, take_session_id),
        lambda: _word_seen(database, actor_id, sessions))
    if isinstance(message, dict):
        changed = message.pop("changed_at", None) or message.get("published_at")
        message["unseen"] = watched is None or newer_than_seen(
            changed, watched.get(str(message.get("take_session_id") or "")))
    return {
        "journey_next_steps_seen": seen,
        "coach_message": message,
    }
