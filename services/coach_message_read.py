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
  `results_published_at` counts, and the latest such Take wins.
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


def coach_message_for(database: Any, sessions: Any) -> Optional[dict]:
    """{text, video_url, take_index, published_at} for the latest published
    Take, or None when there is none or the coach sent neither words nor a
    video. Best-effort: a failed read is None, never an error.

    A WORD FOR THIS TAKE (founder 2026-09-30, B3; 0403) comes first: where a
    coach shared one on any of the arc's takes, the latest shared word is the
    speaker's coach message; the arc-level publish serves only where none
    exists, until the removals retire it (P2-19)."""
    from services.coach_take_word import latest_shared_word
    word = latest_shared_word(database, sessions)
    if word is not None:
        return word
    latest = _latest_published(sessions)
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
    }


def journey_payload(database: Any, actor_id: str, arc_id: str,
                    take_count: int, sessions: Any) -> dict:
    """The Ideal Text enrichment's `journey` section, for the project OWNER
    (the route refuses anyone else before it runs): whether the guided next
    steps were seen, and the coach's overall message and video (Q1, Final
    Screens L8)."""
    from services.journey_messages import journey_seen
    return {
        "journey_next_steps_seen": journey_seen(
            database, actor_id, arc_id, take_count),
        "coach_message": coach_message_for(database, sessions),
    }
