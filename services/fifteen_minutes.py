"""The proverbial 15 minutes (founder 2026-10-26, N180: "learn here the base
and then go and testing real life"; words signed in N183).

Once a day, after about 15 minutes in the app, Will says so in the chat:
"That's your 15 minutes for today." and "Now go and live it, away from the
phone." Nothing is locked and the message box stays. The app counts the
minutes and asks for the line only at a quiet moment, never during a Take,
the processing, the Feedback walk or any lens; this module writes the two
bubbles, at most once per day of the speaker's own calendar.

Its own ring row, ``fifteen_minutes``: ring 6 (founder only) first, then
everyone from the admin rings page.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from typing import Any

FEATURE = "fifteen_minutes"
#: The signed words (N183). No new words without the founder's OK.
COPY = {
    "enough": "That's your 15 minutes for today.",
    "go": "Now go and live it, away from the phone.",
}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAMESPACE = uuid.UUID("3b8e5f21-6c47-4d09-9a1e-c2f7d4085b63")


class FifteenError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def enabled(database: Any, user_id: Any) -> bool:
    """Is the line on for this person? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)


def _their_day(day: Any) -> date:
    """The speaker's own calendar day, from the app; within a day of the
    server's, so a wrong clock cannot write tomorrow's line today."""
    if not isinstance(day, str) or not _DAY.match(day):
        raise FifteenError("INVALID_DAY", "Unknown day.")
    try:
        theirs = date.fromisoformat(day)
    except ValueError as error:
        raise FifteenError("INVALID_DAY", "Unknown day.") from error
    if abs((theirs - datetime.now(timezone.utc).date()).days) > 1:
        raise FifteenError("INVALID_DAY", "Unknown day.")
    return theirs


def say_enough(database: Any, user_id: str, day: Any) -> list[dict]:
    """The two bubbles for ``day``, at the bottom of the thread; the same
    day again writes nothing (the rows' ids are the day's)."""
    if not enabled(database, user_id):
        raise FifteenError("NOT_FOUND", "Not found.", 404)
    theirs = _their_day(day)
    from services.lounge_messages import stamp_after, thread_stamp
    key = f"{user_id}:{theirs.isoformat()}"
    first = str(uuid.uuid5(_NAMESPACE, f"{key}:1"))
    if database.get_lounge_message_by_client_id(str(user_id), first):
        return []
    at = thread_stamp(database, user_id)
    rows = [{"client_id": first, "role": "bot", "kind": "text", "body": COPY["enough"],
             "metadata": {"fifteen_minutes": theirs.isoformat()}, "client_created_at": at},
            {"client_id": str(uuid.uuid5(_NAMESPACE, f"{key}:2")), "role": "bot",
             "kind": "text", "body": COPY["go"],
             "metadata": {"fifteen_minutes": theirs.isoformat()},
             "client_created_at": stamp_after(at)}]
    return database.insert_lounge_messages(str(user_id), rows) or []
