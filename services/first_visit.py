"""Where people leave between the landing page and their first feedback
(founder 2026-10-29, N271: "introduce the counting where the people
leave!"). The founder's only; no speaker sees it.

Each step is a number a day and nothing else: no account, no IP address, no
device. The frontend counts a step once per browser tab, and only for a
visitor without an account. The sign-up screen and the accounts made come
from their own count (services/signup_count.py, N207 item 6), so the founder
reads the whole path in one place. Migration the_first_visit_is_counted.sql.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from services import signup_count

logger = logging.getLogger(__name__)

#: The steps this service keeps, in the order a first visit meets them. The
#: migration's CHECK holds the same list.
STEPS = ("landing", "enter", "agreed", "recording", "recorded", "ready", "walk")

#: The whole path as the founder reads it: these steps, with the sign-up
#: screen ("signup_seen") and the accounts made ("account_made") between the
#: result and the walk.
PATH = ("landing", "enter", "agreed", "recording", "recorded", "ready",
        "signup_seen", "account_made", "walk")


def step(database: Any, name: str) -> bool:
    """One more visitor reached ``name`` today. False for a step this
    service does not know. Best-effort: a count that fails is lost, never
    the screen."""
    if name not in STEPS:
        return False
    try:
        database.client.rpc("first_visit_step_v1", {"p_step": name}).execute()
    except Exception as error:  # noqa: BLE001 -- a count, never the screen
        logger.warning("first visit count: not kept: %s", type(error).__name__)
    return True


def counts(database: Any, *, days: int = 30, today: Optional[date] = None) -> dict:
    """The last ``days`` days (UTC, today included): every step of the path
    in all (``path``) and per day (``days``, newest first), and the accounts
    made by way (``ways``)."""
    days = max(1, min(int(days), signup_count.MOST_DAYS))
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=days - 1)
    rows = database.client.rpc("first_visit_counts_v1", {"p_since": since.isoformat()}).execute().data or []
    signup = signup_count.counts(database, days=days, today=today)
    per_day: dict[str, dict[str, int]] = {}
    for row in rows:
        name = str(row.get("step") or "")
        if name in STEPS:
            day = per_day.setdefault(str(row["day"]), {})
            day[name] = day.get(name, 0) + int(row.get("n") or 0)
    for day in signup["days"]:
        steps = per_day.setdefault(day["day"], {})
        steps["signup_seen"] = day["seen"]
        steps["account_made"] = day["made"]
    total = {name: sum(day.get(name, 0) for day in per_day.values()) for name in PATH}
    return {
        "since": since.isoformat(),
        "path": [{"step": name, "n": total[name]} for name in PATH],
        "ways": signup["total"]["ways"],
        "days": [{"day": d, "steps": {name: per_day[d].get(name, 0) for name in PATH}}
                 for d in sorted(per_day, reverse=True)],
    }
