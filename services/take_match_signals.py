"""How each person speaks and progresses, for the matching after a Take
(founder, the Claude Code chat, 4 November 2026, N481 item 2). Read from
what Willfidence already keeps (migration the_machine_reads_willfidence),
over a person's last ``LAST_TAKES`` Takes:

  * ``skill``    their speaking skills: the mean willfidence of their
                 measured Takes (``v4_willfidence_takes``, status
                 "measured"); None before their first.
  * ``pace``     how fast they progress: how much that willfidence moves
                 from one Take to the next (the least-squares slope over
                 their measured Takes, oldest first), pulled toward no
                 change by how few Takes it rests on, so noise is not read
                 as speed (audit, 4 November 2026); None before five.
  * ``takes``    how many measured Takes the two rest on.
  * ``profile``  their communication profile: the mean of each moment's
                 reads (``v4_willfidence_reads``: sound, fillers, hedging,
                 slide fit, holding together), the keys it has.

All of it is 0 to 1 (the pace, a change per Take), never shown to anyone,
the person included (Never 1; N463 item 4), and kept with each suggestion
for WillpowerLab's review. Reads only: no provider call, nothing written.

Off until the Terms and the Privacy policy every speaker accepts say it and
are signed (N481 item 4): ``is_on`` reads ``TAKE_MATCH_SKILLS``, unset by
default; while it is off the matching weighs knowledge only.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Optional

from services.chats import SESSIONS, _rows, _table

logger = logging.getLogger(__name__)

TAKES = "v4_willfidence_takes"
READS = "v4_willfidence_reads"
READ_VERSION = "willfidence-v1-machine"
#: How many of a person's newest Takes are read.
LAST_TAKES = 10
#: The fewest measured Takes a pace is read from.
MIN_PACE_TAKES = 5
#: How strongly a pace is pulled toward no change: the spread of Take
#: positions (Σ(x − x̄)²) worth of evidence it takes to count half. Ten is
#: five Takes' worth.
PACE_PRIOR = 10.0
#: Ids per read, as ``db._chunks``; Takes per read of their moments, which
#: run to dozens a Take, so ``MAX_ROWS`` holds them all.
CHUNK, MOMENT_CHUNK = 100, 25
#: The moment reads the profile is made of (N481 item 2, proposed).
PROFILE_KEYS = ("s", "filler", "hedging", "slide_fit", "holding_together")
#: How many rows any one read takes, at most.
MAX_ROWS = 2000


def is_on() -> bool:
    """Whether the matching may weigh skills, pace and the profile: only
    once the text saying so is signed and published (N481 item 4)."""
    return os.environ.get("TAKE_MATCH_SKILLS", "").strip().lower() in ("1", "true", "yes", "on")


def slope(values: list[float]) -> Optional[float]:
    """The least-squares change per step of ``values`` (oldest first),
    pulled toward 0 by ``PACE_PRIOR``, or None with fewer than
    ``MIN_PACE_TAKES``. Pure."""
    n = len(values)
    if n < MIN_PACE_TAKES:
        return None
    mean_x, mean_y = (n - 1) / 2, sum(values) / n
    spread = sum((x - mean_x) ** 2 for x in range(n))
    raw = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values)) / spread
    return raw * spread / (spread + PACE_PRIOR)


def _number(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    kept = [v for v in values if v is not None]
    return sum(kept) / len(kept) if kept else None


def _chunks(ids: list[str], size: int = CHUNK) -> list[list[str]]:
    return [ids[i:i + size] for i in range(0, len(ids), size)]


def _newest_takes(database: Any, user_ids: list[str]) -> dict[str, list[str]]:
    """Each person's newest Takes, oldest first; read in parts, a fair share
    of rows for each, so the busiest people cannot crowd out the rest."""
    takes: dict[str, list[str]] = {}
    for part in _chunks(user_ids):
        for r in _rows(_table(database, SESSIONS).select("id,user_id,created_at")
                       .in_("user_id", part).order("created_at", desc=True)
                       .limit(len(part) * LAST_TAKES * 3)):
            mine = takes.setdefault(str(r.get("user_id")), [])
            if len(mine) < LAST_TAKES:
                mine.append(str(r["id"]))
    return {uid: list(reversed(ids)) for uid, ids in takes.items()}


def _profile(reads: list[dict]) -> dict[str, float]:
    out = {}
    for key in PROFILE_KEYS:
        value = _mean(_number(r.get(key)) for r in reads)
        if value is not None:
            out[key] = round(value, 4)
    return out


def of(database: Any, user_ids: list[str]) -> dict[str, dict]:
    """{user_id: {"skill", "pace", "profile"}} for each of ``user_ids``.
    A read that fails gives nothing for anyone and is logged: the matching
    then weighs knowledge only, and never breaks the page after a Take."""
    people = sorted({str(u) for u in user_ids if u})
    blank: dict[str, dict[str, Any]] = {
        uid: {"skill": None, "pace": None, "profile": {}, "takes": 0} for uid in people}
    if not people:
        return blank
    try:
        takes = _newest_takes(database, people)
        ids = [t for ts in takes.values() for t in ts]
        if not ids:
            return blank
        measured: dict[str, Optional[float]] = {}
        reads: dict[str, list[dict]] = {}
        for part in _chunks(ids):
            measured.update({str(r["take_session_id"]): _number(r.get("willfidence")) for r in _rows(
                _table(database, TAKES).select("take_session_id,willfidence")
                .in_("take_session_id", part).eq("read_version", READ_VERSION)
                .eq("status", "measured").limit(MAX_ROWS))})
        for part in _chunks(ids, MOMENT_CHUNK):
            for r in _rows(_table(database, READS)
                           .select("take_session_id," + ",".join(PROFILE_KEYS))
                           .in_("take_session_id", part).eq("read_version", READ_VERSION)
                           .limit(MAX_ROWS)):
                reads.setdefault(str(r["take_session_id"]), []).append(r)
    except Exception:
        logger.warning("take_match_signals: the reads failed; knowledge only", exc_info=True)
        return blank
    for uid, ts in takes.items():
        line = [v for v in (measured.get(t) for t in ts) if v is not None]
        blank[uid] = {"skill": _mean(line), "pace": slope(line), "takes": len(line),
                      "profile": _profile([r for t in ts for r in reads.get(t, [])])}
    return blank


def profile_distance(a: dict[str, float], b: dict[str, float]) -> Optional[float]:
    """How far apart two profiles are, 0 alike to 1 opposite, on the keys
    both have; None when they share none. Pure."""
    keys = [k for k in PROFILE_KEYS if k in a and k in b]
    if not keys:
        return None
    return round((sum((a[k] - b[k]) ** 2 for k in keys) / len(keys)) ** 0.5, 4)
