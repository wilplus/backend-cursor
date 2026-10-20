"""Every goal a speaker has had, and a card for the coach when it changes
(WIL-74 phase 1, founder 2026-10-19, words signed the same day). Table:
user_goal_history; the current goal stays in user_settings.profile_goal.

``record`` is called by every goal writer (the chat's goal intercept and
POST /v2/user/profile) after the goal is saved. It is best-effort and never
raises: the goal is saved either way.

The coach's card is a row in the coach's own Lounge (coaches are users):

    {speaker} has a new goal
    Before: {old goal}
    Now: {new goal}

``{speaker}`` is the pseudonym the coach panel shows, never the speaker's
name. One card per speaker per coach per day: a second change the same day
rewrites it with the latest goal and keeps the day's first "Before". Every
active coach gets it (solo-coach beta: every speaker is in every coach's
scope, routes/v2/coach.py). The goal is the speaker's own words, echoed,
never graded (AC-9). The card carries the speaker's id in
``lounge_messages.about_user_id``, so deleting the speaker's account deletes
it too.

The chat knows the history: ``history_lines`` is read into the speaker's
status card (``chat_app_context``), so "what were my goals?" is answered
from it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("0c4f8e21-5a6d-4b39-8f1e-2d7a9c3b6e54")
SOURCES = ("chat", "profile")
#: The signed words (founder 2026-10-19). No new words without the founder's OK.
COPY = {
    "title": "{speaker} has a new goal",
    "before": "Before: {goal}",
    "now": "Now: {goal}",
    "open": "Open speaker",
}
CARD = "goal_change"


def card_body(speaker: str, before: Optional[str], now: str) -> str:
    """The card's words. Pure."""
    lines = [COPY["title"].format(speaker=speaker)]
    if before:
        lines.append(COPY["before"].format(goal=before))
    lines.append(COPY["now"].format(goal=now))
    return "\n".join(lines)


def _card(database: Any, coach_id: str, speaker_id: str, pseudonym: str,
          before: Optional[str], now: str, at: datetime) -> dict:
    client_id = str(uuid.uuid5(
        _NAMESPACE, f"{coach_id}:{speaker_id}:{at.date().isoformat()}"))
    held = database.get_lounge_message_by_client_id(coach_id, client_id)
    if held:
        before = (held.get("metadata") or {}).get("before", before)
    meta = {"card": CARD, "speaker": pseudonym, "speaker_id": speaker_id,
            "before": before, "now": now}
    body = card_body(pseudonym, before, now)
    if held:
        database.rewrite_lounge_message(coach_id, client_id, body, meta)
    else:
        database.insert_lounge_messages(coach_id, [{
            "client_id": client_id, "role": "bot", "kind": "text", "body": body,
            "metadata": meta, "client_created_at": at.isoformat(),
            "about_user_id": speaker_id}])
    return meta


def tell_coaches(database: Any, speaker_id: str, before: Optional[str], now: str) -> int:
    """The card in every active coach's Lounge; how many got it."""
    from services.coach_pseudonym import coach_pseudonym
    pseudonym = coach_pseudonym(speaker_id)
    at = datetime.now(timezone.utc)
    told = 0
    for coach_id in database.active_coach_user_ids():
        if coach_id == speaker_id:
            continue  # a coach changing their own goal
        try:
            _card(database, coach_id, speaker_id, pseudonym, before, now, at)
            told += 1
        except Exception as error:  # noqa: BLE001 -- one coach's card never stops the next
            logger.warning("goal history: card not written coach=%s: %s", coach_id, error, exc_info=True)
    return told


def record(database: Any, user_id: Any, before: Optional[str], now: Optional[str],
           source: str) -> bool:
    """A saved goal joins the history and the coaches hear of it. Nothing
    happens when the goal did not change. Never raises."""
    before = (before or "").strip() or None
    now = (now or "").strip()
    if not user_id or not now or now == before or source not in SOURCES:
        return False
    try:
        if not database.insert_goal_history({
                "user_id": str(user_id), "goal": now, "previous_goal": before,
                "source": source}):
            return False
        tell_coaches(database, str(user_id), before, now)
        return True
    except Exception as error:  # noqa: BLE001 -- the goal is saved either way
        logger.warning("goal history: not recorded user=%s: %s", user_id, error, exc_info=True)
        return False


def record_later(database: Any, user_id: Any, before: Optional[str],
                 now: Optional[str], source: str) -> None:
    """``record`` off the request (finding the coaches reads the account
    list), so saving a goal never waits on it."""
    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(lambda: record(database, user_id, before, now, source),
                            name="goal-history")
    except Exception as error:  # noqa: BLE001 -- the goal is saved either way
        logger.warning("goal history: not started user=%s: %s", user_id, error, exc_info=True)


def history_lines(database: Any, user_id: Any, limit: int = 5) -> list[str]:
    """The speaker's earlier goals, newest first, as plain lines with their
    date, for the chat's status card. [] when there are none."""
    rows = database.list_goal_history(str(user_id), limit=limit) or []
    return [f"{str(r.get('changed_at') or '')[:10]}: {r.get('goal')}"
            for r in rows if r.get("goal")]
