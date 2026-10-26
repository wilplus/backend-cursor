"""One message when the coach is done (founder 2026-10-26, N171 items 3 and
4, N174 item 2).

Until now each message a coach shared (the Take's word, or the answer on one
moment) sent the speaker its own WhatsApp and its own email at once: a coach
who answered five moments and left a word made the phone buzz six times and
sent six emails. Now:

  * ONE MESSAGE A SITTING. Every share is counted against the speaker and
    pushes the message back; it goes once the coach has shared nothing more
    with that speaker for ``QUIET_SECONDS`` (10 minutes), for all of it, its
    link naming the Take of the last share.
  * NOTHING WHEN ALREADY SEEN. When it is due and the speaker has opened the
    coach's feedback in the app meanwhile (the project's orange dot is
    cleared, ``coach_feedback_signal``), nothing goes.
  * ONE CHANNEL. With a WhatsApp number, the WhatsApp and no email; without
    one, the email. When the WhatsApp cannot be sent (off, refused), the
    email goes instead.

The count and the latest Take wait in Redis (``coach-notice:<speaker>``, a
day at most) and the send is a delayed job on the pipeline queue, one per
share: each share gets its own token, its job carries it, and only the job
of the latest share sends, so a sitting sends once with no clock to compare.
A ``SET NX`` per token keeps a job that runs twice from sending twice.

Best-effort throughout: the coach's save never waits on it or fails on it
(LIVE LOOP). Without the queue (no Redis, or an enqueue that fails) the share
is told at once, as before, through the same one channel.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: How long the coach must be quiet before the speaker is told (N171 item 4).
QUIET_SECONDS = 600
#: How long a sitting's count may wait in Redis.
_KEEP_SECONDS = 24 * 3600
_JOB = "services.coach_feedback_notice.send_when_quiet"


def _key(user_id: str) -> str:
    return f"coach-notice:{user_id}"


def _store() -> Any:
    """The queue's Redis connection, or None."""
    from services import job_queue
    return job_queue.get_redis()


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value or "")


def coach_shared(database: Any, *, user_id: Any, take_session_id: Any,
                 moments: int) -> None:
    """A coach shared their word on this Take (``moments=0``) or their answer
    on one moment (``moments=1``) with this speaker. Never raises."""
    if not user_id or not take_session_id:
        return
    user_id, take = str(user_id), str(take_session_id)
    try:
        conn = _store()
        if conn is not None:
            key, token = _key(user_id), uuid.uuid4().hex
            conn.hincrby(key, "moments", int(moments))
            conn.hset(key, mapping={"take": take, "latest": token})
            conn.expire(key, _KEEP_SECONDS)
            from services import job_queue
            if job_queue.enqueue(_JOB, user_id, token, delay_seconds=QUIET_SECONDS,
                                 rq_job_id=f"coach-notice-{token}"):
                _log.info("coach notice: share %s counted for user=%s", token, user_id)
                return
            conn.hincrby(key, "moments", -int(moments))
    except Exception as e:  # noqa: BLE001 -- told at once instead
        _log.warning("coach notice: could not wait for the sitting user=%s: %s",
                     user_id, type(e).__name__)
    _log.info("coach notice: no queue, telling user=%s at once", user_id)
    threading.Thread(target=deliver, args=(database, user_id, take, int(moments)),
                     name="coach-notice", daemon=True).start()


def send_when_quiet(user_id: str, token: str, database: Any = None) -> str:
    """The delayed job of one share. Sends only when it is the job of the
    sitting's latest share, once. Returns what happened."""
    try:
        conn = _store()
        if conn is None:
            return "no_store"
        key = _key(str(user_id))
        data = {_text(k): _text(v) for k, v in (conn.hgetall(key) or {}).items()}
        if not data:
            return "nothing_waiting"
        if data.get("latest") != str(token):
            return "coach_not_done"
        if not conn.set(f"coach-notice-sent:{token}", "1", nx=True, ex=_KEEP_SECONDS):
            return "already_sent"
        moments = int(data.get("moments") or 0)
        conn.hincrby(key, "moments", -moments)
        if database is None:
            from services.db import db as database
        outcome = deliver(database, str(user_id), data.get("take") or "", moments)
        _log.info("coach notice: user=%s share=%s moments=%s: %s",
                  user_id, token, moments, outcome)
        return outcome
    except Exception as e:  # noqa: BLE001 -- the Lounge bubble is there either way
        _log.warning("coach notice: job failed user=%s share=%s: %s",
                     user_id, token, e, exc_info=True)
        return "failed"


def deliver(database: Any, user_id: str, take_session_id: str, moments: int) -> str:
    """The one message: none when already seen; else the WhatsApp, else the
    email. Returns what happened. Never raises."""
    try:
        if _already_seen(database, user_id, take_session_id):
            return "seen"
        from services.whatsapp_notify import notify_coach_feedback_in
        if notify_coach_feedback_in(database, user_id, take_session_id or None):
            return "whatsapp"
        from services.coach_feedback_email import send_coach_feedback_email
        return "email:" + send_coach_feedback_email(
            database, take_session_id=take_session_id, moments=moments)
    except Exception as e:  # noqa: BLE001 -- the Lounge bubble is there either way
        _log.warning("coach notice: delivery failed user=%s: %s", user_id, e)
        return "failed"


def _already_seen(database: Any, user_id: str, take_session_id: str) -> bool:
    """The project's orange dot is cleared: the speaker opened everything the
    coach shared. Unknown (no project, a failed read) is not seen."""
    session: Optional[dict] = None
    if take_session_id:
        session = database.v2_get_session_by_id(str(take_session_id)) or {}
    arc = str((session or {}).get("arc_id") or "")
    if not arc:
        return False
    from services.coach_feedback_signal import lounge_flags
    flags = lounge_flags(database, user_id)
    return arc in flags and flags[arc] is False
