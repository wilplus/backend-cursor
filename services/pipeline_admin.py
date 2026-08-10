"""The admin panel's read of the job queue. Task IV, Tier 1.

A THIN LAYER ON PURPOSE. `queue_health()` already answers "is anyone
waiting?" and `sweep_stale_jobs()` already recovers lost work; this module
adds the one thing they do not have — a list of individual jobs — and
otherwise gets out of the way. The panel is a new DOOR onto existing
machinery, not a second implementation of it.

AC-9. These are PLUMBING COUNTERS ABOUT JOBS, not reads on a speaker: status,
stage, attempts, timings. No score, no rank, no transcript, no `power_score`.
The fence forbids surfacing scores/verdicts/numbers to USERS, and nothing here
is user-facing or speaker-level — but the way that stays true is the
projection in `db._ADMIN_JOB_FIELDS`, which is a fixed field list rather than
`select("*")`.

WHY user_id IS INCLUDED AND WHAT IT IS FOR. An operator whose queue is stuck
needs to know whether the stall hits one account or everyone — that is the
difference between a user-specific bad upload and a dead worker. It is an
opaque UUID, carries no personal data, and the panel must not resolve it to a
name or email: identifying WHOSE recording is stuck is not needed to decide
whether to sweep.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.db import db

logger = logging.getLogger(__name__)

# Mirrors the data-layer cap. Stated twice deliberately: the route validates
# early so a bad request is rejected with a clear message, and db.py clamps
# regardless so no caller can ever exceed it.
MAX_LIMIT = 100
DEFAULT_LIMIT = 50

# The statuses a caller may filter on. A closed set, so a typo ('complete')
# returns an error rather than an empty list that reads as "no jobs".
STATUSES = ("pending", "processing", "completed", "failed")


def list_jobs_for_admin(
    *, status: Optional[str] = None, limit: int = DEFAULT_LIMIT,
    before: Optional[str] = None,
) -> Dict[str, Any]:
    """Recent jobs, newest first, plus the cursor for the next page.

    Returns ``{"jobs": [...], "next_before": <enqueued_at|None>}``.
    ``next_before`` is None when this is the last page, so the caller never
    has to infer "am I done" from a short page — a page can be short because
    the queue drained between requests.

    Never raises: an ops surface that 500s during an incident is a surface
    nobody can use during an incident.
    """
    if status is not None and status not in STATUSES:
        raise ValueError(
            f"unknown status {status!r}; expected one of {', '.join(STATUSES)}")
    try:
        capped = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    except (TypeError, ValueError):
        capped = DEFAULT_LIMIT

    # Ask for one extra row to learn whether another page exists WITHOUT a
    # count query. A COUNT over a mutating queue is both slower and less
    # honest — it describes a moment that has already passed.
    rows: List[Dict[str, Any]] = db.list_processing_jobs(
        status=status, limit=capped + 1, before=before) or []

    has_more = len(rows) > capped
    jobs = rows[:capped]
    next_before = jobs[-1].get("enqueued_at") if (has_more and jobs) else None
    return {"jobs": jobs, "next_before": next_before, "count": len(jobs)}
