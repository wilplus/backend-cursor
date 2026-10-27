"""How many people reach the sign-up screen, and how many make an account,
by way (founder 2026-10-26, N207 item 6; N174 item 6: "First count how many
people leave at the sign-up screen"). The founder's only; no speaker sees it.

The screen's count is a number a day and nothing else: no account, no IP
address, no device. The accounts are read from Supabase's own list, by the
way it records (email, google, linkedin_oidc). Migration
the_sign_up_screen_is_counted.sql.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: How far back the founder can look.
MOST_DAYS = 365


def seen(database: Any) -> None:
    """One more opening of the sign-up screen today. Best-effort: a count
    that fails is lost, never the screen."""
    try:
        database.client.rpc("signup_screen_seen_v1", {}).execute()
    except Exception as error:  # noqa: BLE001 -- a count, never the screen
        logger.warning("signup count: not kept: %s", type(error).__name__)


def counts(database: Any, *, days: int = 30, today: Optional[date] = None) -> dict:
    """The last ``days`` days (UTC, today included), per day and in all:
    how many opened the sign-up screen (``seen``) and how many made an
    account (``made``), with the accounts by way (``ways``)."""
    days = max(1, min(int(days), MOST_DAYS))
    since = (today or datetime.now(timezone.utc).date()) - timedelta(days=days - 1)
    rows = database.client.rpc("signup_counts_v1", {"p_since": since.isoformat()}).execute().data or []
    per_day: dict[str, dict] = {}
    total: dict = {"seen": 0, "made": 0, "ways": {}}
    for row in rows:
        n = int(row.get("n") or 0)
        day = per_day.setdefault(str(row["day"]), {"day": str(row["day"]), "seen": 0, "made": 0, "ways": {}})
        if row.get("step") == "seen":
            day["seen"] += n
            total["seen"] += n
        elif row.get("step") == "made":
            way = str(row.get("way") or "email")
            day["made"] += n
            day["ways"][way] = day["ways"].get(way, 0) + n
            total["made"] += n
            total["ways"][way] = total["ways"].get(way, 0) + n
    return {"since": since.isoformat(), "total": total,
            "days": [per_day[d] for d in sorted(per_day, reverse=True)]}
