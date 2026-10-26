"""The founder's "Homework" email, once a day (founder 2026-10-26, N174
item 3).

Until now every spoken Take sent to the coach queue sent ADMIN_EMAIL its own
"A student has completed a homework lesson." email; with fifty speakers that
is fifty emails a day. Now each Take is noted, and once a day, from
``SEND_HOUR`` in the booking page's time zone (the founder's own, the host
of the lessons), one email lists the Takes since the last one, a row per
student. A day with no Takes sends nothing. The coach queue in the app shows
every Take at once, as before.

The Takes wait in Redis (``homework-digest:pending``, a week at most); the
worker's minute sweep sends the email (``sweep_due``), and a ``SET NX`` per
day keeps it to one. Takes that arrive after the day's email wait for the
next. A re-read never counts (``lab_send._notify_admin`` already drops it).

Best-effort: never raises into the hand-off. Without Redis the Take's own
email goes at once, as before.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from config import Config

_log = logging.getLogger(__name__)

#: The hour of the day, in the founder's time zone, the email goes.
SEND_HOUR = 8
_PENDING = "homework-digest:pending"
_KEEP_SECONDS = 7 * 24 * 3600
_ZONE_CACHE: dict[str, Any] = {}
_ZONE_TTL_SECONDS = 3600


def _store() -> Any:
    from services import job_queue
    return job_queue.get_redis()


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value or "")


def record(session_id: str, user_id: str, moments: int,
           now: Optional[datetime] = None) -> bool:
    """Note one spoken Take for the day's email. False when it could not be
    noted (no Redis, a failed write): the caller then sends its own email."""
    try:
        conn = _store()
        if conn is None:
            return False
        moment = now or datetime.now(timezone.utc)
        conn.rpush(_PENDING, json.dumps({
            "session_id": str(session_id), "user_id": str(user_id),
            "moments": int(moments or 0), "at": moment.isoformat()}))
        conn.expire(_PENDING, _KEEP_SECONDS)
        return True
    except Exception as e:  # noqa: BLE001 -- the Take's own email instead
        _log.warning("homework digest: could not note take=%s: %s",
                     session_id, type(e).__name__)
        return False


def _zone() -> ZoneInfo:
    """The booking page's time zone (the founder's), cached for an hour;
    UTC when it is not set or unreadable."""
    cached = _ZONE_CACHE.get("zone")
    if cached and time.monotonic() - cached[1] < _ZONE_TTL_SECONDS:
        return cached[0]
    zone = ZoneInfo("UTC")
    try:
        from services.booking import get_settings
        zone = ZoneInfo(str(get_settings().get("timezone") or "UTC"))
    except Exception as e:  # noqa: BLE001 -- unset or unreadable: UTC
        _log.info("homework digest: using UTC (%s)", type(e).__name__)
    _ZONE_CACHE["zone"] = (zone, time.monotonic())
    return zone


def sweep_due(now: Optional[datetime] = None, database: Any = None) -> str:
    """Each minute, from the worker's sweep: send the day's email once its
    hour has come. Returns what happened. Never raises."""
    try:
        if not Config.SEND_EMAILS:
            return "send_emails_off"
        conn = _store()
        if conn is None:
            return "no_store"
        local = (now or datetime.now(timezone.utc)).astimezone(_zone())
        if local.hour < SEND_HOUR:
            return "not_yet"
        day = local.date().isoformat()
        if not conn.set(f"homework-digest:day:{day}", "1", nx=True, ex=3 * 24 * 3600):
            return "already_today"
        sending = f"homework-digest:sending:{day}"
        try:
            conn.rename(_PENDING, sending)
        except Exception:  # noqa: BLE001 -- no Takes noted since the last email
            return "nothing"
        conn.expire(sending, _KEEP_SECONDS)
        items = [json.loads(_text(raw)) for raw in conn.lrange(sending, 0, -1) or []]
        if database is None:
            from services.db import db as database
        outcome = send(database, items, local)
        if outcome == "failed":
            # Back on the list for the next day's email, never lost.
            for item in items:
                conn.rpush(_PENDING, json.dumps(item))
            conn.expire(_PENDING, _KEEP_SECONDS)
        conn.delete(sending)
        _log.info("homework digest: %s takes on %s: %s", len(items), day, outcome)
        return outcome
    except Exception as e:  # noqa: BLE001 -- the coach queue shows every Take
        _log.warning("homework digest: sweep failed: %s", e, exc_info=True)
        return "failed"


def students(database: Any, items: list[dict]) -> list[dict]:
    """One row per student, in the order they first sent a Take:
    ``{user_id, label, takes, moments}``. The label is "Name (email)", the
    email alone, or the coach pseudonym, never a raw id."""
    from services.coach_pseudonym import coach_pseudonym
    from services.session_publish import _fetch_user_email
    rows: dict[str, dict] = {}
    for item in items:
        user_id = str(item.get("user_id") or "")
        if not user_id:
            continue
        row = rows.get(user_id)
        if row is None:
            email = (_fetch_user_email(user_id) or "").strip()
            name = ""
            try:
                name = ((database.v2_get_student_details(user_id) or {}).get("name") or "").strip()
            except Exception:  # noqa: BLE001 -- the email alone will do
                pass
            label = (f"{name} ({email})" if name and email
                     else email or name or coach_pseudonym(user_id))
            row = rows[user_id] = {"user_id": user_id, "label": label,
                                   "takes": 0, "moments": 0}
        row["takes"] += 1
        row["moments"] += int(item.get("moments") or 0)
    return list(rows.values())


def send(database: Any, items: list[dict], local: datetime) -> str:
    """One email to ADMIN_EMAIL listing ``items``. "sent", or why not."""
    rows = students(database, items)
    if not rows:
        return "nothing"
    from services.assignment_email import build_admin_homework_digest_email_html
    from services.email_service import send_email_resend
    base = (Config.FRONTEND_URL or "").rstrip("/")
    for row in rows:
        row["url"] = f"{base}/admin/students/{row['user_id']}" if base else "#"
    takes = sum(r["takes"] for r in rows)
    date_label = f"{local:%A} {local.day} {local:%B}"
    mail = build_admin_homework_digest_email_html(rows=rows, date_label=date_label)
    try:
        send_email_resend(to=Config.ADMIN_EMAIL,
                          subject=f"Homework, {date_label}: {takes} {'Take' if takes == 1 else 'Takes'}",
                          html=mail["html"], text=mail["text"])
    except Exception as e:  # noqa: BLE001 -- logged; the queue shows the Takes
        _log.warning("homework digest: send failed: %s", e)
        return "failed"
    return "sent"
