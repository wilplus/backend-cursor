"""Does the registry say this product purpose may run today?

WHY THIS EXISTS. routes/phase2_guard.py's `operational_purpose_disabled`
promised, in its own docstring, to "fail closed WHILE a registry-only product
purpose is not operational". It did not read the registry — it returned 410
unconditionally. That was honest enough while the answer could only be no, but
it meant the switch and the fact it claimed to reflect were two different
things, kept in step by hand. 0335 makes `personalized_exercise_recommendation`
operational, and a hand-kept switch would then have to be flipped in a separate
deploy, in the right order, or the routes would either stay shut on a ready
system or open onto an unprepared one.

So the guard now asks. One source of truth: the same registry row the database
functions consult when they decide whether to issue a permit. The route and the
permit path can no longer disagree.

FAIL CLOSED, TWICE OVER. A missing row, an unreadable registry, a phase-2
purpose, `operational = false` — every one of them answers no. Only an explicit
phase-1, operational, authorizing row opens the door. The table's own
`processing_purpose_operational_invariant` CHECK guarantees that such a row
also carries its capability, retention, deletion and rights versions, so this
does not have to re-check them and cannot drift from what the database
enforces.

THE CACHE. This is asked on every request to a gated route, and the answer
changes only when a migration runs. A short TTL keeps that from becoming a
database read per request while still letting a deliberate flip take effect
within a minute — including a flip to FALSE, which is the emergency stop and
must not need a redeploy. Failures are never cached: a blip closes the door for
that request and the next one asks again, rather than latching shut for a
minute.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Long enough to collapse a burst of requests, short enough that flipping the
#: switch off is felt quickly. Not tunable by environment on purpose: a gate
#: whose responsiveness varies per deployment is a gate nobody can reason about.
CACHE_TTL_SECONDS = 60.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, bool]] = {}


def purpose_is_operational(
    purpose_id: str, *, database: Any = None, now: Optional[float] = None,
) -> bool:
    """True only if the registry says this purpose is phase-1 and operational."""
    if not purpose_id:
        return False
    moment = time.monotonic() if now is None else now
    with _lock:
        cached = _cache.get(purpose_id)
        if cached and moment - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    if database is None:
        from services.db import db as database

    row = database.get_processing_purpose(purpose_id)
    if not isinstance(row, dict):
        # None is "could not establish" as well as "no such purpose". Both are
        # a closed door, and neither is cached — a registry blip must not latch
        # the feature off for the rest of the TTL.
        return False

    answer = (
        row.get("phase") == "phase1"
        and row.get("operational") is True
        and row.get("authorizes_processing") is True
    )
    with _lock:
        _cache[purpose_id] = (moment, answer)
    return answer


def forget_cached_purposes() -> None:
    """Drop the cache. For tests, and for anything that knows the registry
    just changed and should not wait out the TTL."""
    with _lock:
        _cache.clear()
