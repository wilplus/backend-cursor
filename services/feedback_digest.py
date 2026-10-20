"""The weekly note to the founder (founder 2026-10-20, principles: "a short
note in your chat once a week", "let the next Take answer it", "change
something when the same thing is missing three times").

Five lines in each active admin's own Lounge, once per ISO week, posted
after the first closing summary of the week (``take_summary`` calls
``post_later``), so there is no job to schedule:

    Feedback, the last 7 days
    The voice rose since the last Take in X of Y Takes
    Asked "Did this help?": N · it helped: M
    What would help:
    “…” (up to three, newest first)

For the founder only; no speaker ever sees a number (CLAUDE.md, Never 1).
Best-effort: it never raises into the summary.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("9a1e2c47-3b6d-4f80-a2c5-6d9e0b7f3c18")
_DAYS = 7
_QUOTES = 3
#: Finding the admins reads the account list: once every few hours.
_ADMINS_TTL = 6 * 3600
_admins: tuple[float, list[str]] = (0.0, [])


def note(summaries: list[dict], checks: list[dict]) -> str:
    """The note's words from a week of summary metadata and answers. Pure."""
    moved = [s for s in summaries if s.get("moved") in ("rose", "held", "dipped")]
    rose = sum(1 for s in moved if s.get("moved") == "rose")
    answered = [c for c in checks if c.get("helped") is not None]
    helped = sum(1 for c in answered if c.get("helped") is True)
    missing = [c["missing"].strip() for c in checks if (c.get("missing") or "").strip()]
    lines = ["Feedback, the last 7 days",
             f"The voice rose since the last Take in {rose} of {len(moved)} Takes",
             f"Asked \"Did this help?\": {len(answered)} · it helped: {helped}"]
    if missing:
        lines.append("What would help:")
        lines += [f"“{m[:200]}”" for m in missing[:_QUOTES]]
    return "\n".join(lines)


def _admin_ids(database: Any) -> list[str]:
    global _admins
    at, ids = _admins
    if time.monotonic() - at < _ADMINS_TTL:
        return ids
    ids = database.active_admin_user_ids()
    _admins = (time.monotonic(), ids)
    return ids


def post(database: Any, now: datetime | None = None) -> int:
    """This week's note in every admin's Lounge that has none yet; how many
    were written. Nothing when the week has nothing to say."""
    now = now or datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    admins = [a for a in _admin_ids(database)
              if not database.get_lounge_message_by_client_id(
                  a, str(uuid.uuid5(_NAMESPACE, f"{a}:{year}-W{week}")))]
    if not admins:
        return 0
    since = (now - timedelta(days=_DAYS)).isoformat()
    summaries = database.list_take_summaries_since(since)
    checks = database.list_feedback_checks_since(since)
    if not summaries and not checks:
        return 0
    body = note(summaries, checks)
    for admin in admins:
        database.insert_lounge_messages(admin, [{
            "client_id": str(uuid.uuid5(_NAMESPACE, f"{admin}:{year}-W{week}")),
            "role": "bot", "kind": "text", "body": body,
            "metadata": {"note": "feedback_digest", "week": f"{year}-W{week}"},
            "client_created_at": now.isoformat()}])
    return len(admins)


def post_later(database: Any) -> None:
    """``post`` off the request; never raises."""
    def run() -> None:
        try:
            post(database)
        except Exception as error:  # noqa: BLE001 -- the summary is written either way
            logger.warning("feedback digest not posted: %s", error, exc_info=True)
    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(run, name="feedback-digest")
    except Exception as error:  # noqa: BLE001 -- the summary is written either way
        logger.warning("feedback digest not started: %s", error, exc_info=True)
