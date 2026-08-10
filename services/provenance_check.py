"""The RUNTIME half of provenance: the boot check and the row marker.

services/provenance.py is pure — hashing and canonicalisation, no I/O. This
module is the impure counterpart: it reads the recorded hash from
`detector_version`, compares it against the live code, and hands the write
path the (marker, version) pair to stamp onto new rows.

THE CONTRACT (founder decision 2026-08-10 — Option B, mark not refuse):

  * a mismatch NEVER stops the process. The LIVE LOOP fence says never break
    the running record→transcribe→coach→read loop; a mismatch is recoverable
    as long as it is visible and the affected rows are separable.
  * it IS logged CRITICAL, once per process per detector — a level this
    codebase otherwise never uses, so it cannot drown in the warning noise.
  * every row written while the mismatch stands carries provenance='suspect'.

THREE OUTCOMES, and the difference between the last two is the point:

  (marker, version)
  (None, None)      the detector_version TABLE is unreachable (not migrated
                    yet, or the DB read failed). The row stays UNSTAMPED —
                    the same honest NULL as pre-provenance history. Not
                    cached, so the first read after the migration lands
                    picks it up without a restart.
  ('suspect', v?)   the table answered and the answer is bad: no current row
                    for the detector, or the live definition's hash disagrees
                    with the recorded one. UNKNOWN IS SUSPECT (provenance.check).
  ('ok', v)         the live code hashes to its recorded version.

WHY LAZY + CACHED rather than boot-only: dimension_evaluations rows are also
written by the analysis worker, which has its own boot path. Checking on
first stamp means every writer is covered without wiring every entrypoint;
caching means the polled surfaces cost one DB read per process, not one per
request. check_at_boot() exists so the WEB process still gets the CRITICAL
log at a predictable moment instead of on the first coincidental write.
"""
from __future__ import annotations

import logging
from typing import Optional

from services import provenance

logger = logging.getLogger(__name__)

# detector_id -> (marker, version). Only DEFINITE answers are cached — a
# table-missing/unreachable result must stay retryable (see module header).
_CACHE: dict[str, tuple[str, Optional[str]]] = {}


def _read_current_row(detector_id: str) -> Optional[dict]:
    """The current detector_version row, {} when none, None when unreadable.

    Imported lazily: services.db imports half the codebase at module load,
    and this module must stay importable from anywhere (including db.py
    itself) without a cycle.
    """
    try:
        from services.db import db
        res = (db.client.table("detector_version")
               .select("version, definition_hash")
               .eq("detector_id", detector_id)
               .is_("retired_at", "null")
               .order("effective_from", desc=True)
               .limit(1).execute())
        return (res.data or [{}])[0] if res.data is not None else {}
    except Exception as e:
        # Table not migrated yet, or infra. Both mean "nobody looked", which
        # is NULL, not 'suspect' — logged at warning so a permanently missing
        # table is still findable.
        logger.warning("provenance: detector_version unreadable (%s): %s",
                       detector_id, e)
        return None


def status(detector_id: str) -> tuple[Optional[str], Optional[str]]:
    """(marker, version) to stamp on a new measurement row.

    (None, None) = stamp nothing. Never raises.
    """
    cached = _CACHE.get(detector_id)
    if cached is not None:
        return cached
    row = _read_current_row(detector_id)
    if row is None:
        return (None, None)                    # unreadable — NOT cached
    version = row.get("version") or None
    marker, live_hash = provenance.check(detector_id, row.get("definition_hash"))
    if marker == provenance.SUSPECT:
        # CRITICAL on purpose — see module header. Says what to do, because
        # the person reading this at 2am is not the person who wrote it.
        logger.critical(
            "PROVENANCE MISMATCH detector=%s recorded_version=%s "
            "recorded_hash=%s live_hash=%s — the live definition disagrees "
            "with its version stamp. Rows written from now on are marked "
            "provenance='suspect'. Fix: mint the next version in "
            "detector_version (retire the old row, insert the new definition "
            "+ hash); NEVER edit the existing row.",
            detector_id, version, row.get("definition_hash"), live_hash)
    result = (marker, version)
    _CACHE[detector_id] = result
    return result


def stamp(dimension_id: str) -> dict:
    """The provenance fields for ONE dimension_evaluations row, possibly {}.

    {} for dimensions with no registered detector — an honest absence, not a
    default. The caller merges this into the row payload.
    """
    detector_id = provenance.DETECTOR_FOR_DIMENSION.get(dimension_id or "")
    if not detector_id:
        return {}
    marker, version = status(detector_id)
    if marker is None:
        return {}
    return {"provenance": marker, "detector_version": version}


def check_at_boot() -> None:
    """Run the check for every registered detector. NEVER raises.

    Called from app.py right after enforce_at_boot(). Failure to check is
    not failure to boot — that is the whole §5 decision.
    """
    for detector_id in provenance.DETECTORS:
        try:
            marker, version = status(detector_id)
            if marker == provenance.OK:
                logger.info("provenance: %s ok (version=%s)",
                            detector_id, version)
        except Exception as e:                  # pragma: no cover — belt
            logger.warning("provenance: boot check failed for %s: %s",
                           detector_id, e)


def reset_cache() -> None:
    """Tests only. A worker that re-forks gets a fresh module anyway."""
    _CACHE.clear()
