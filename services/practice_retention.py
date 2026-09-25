"""Option A: keep the attempt they chose, let the rest go.

Founder 2026-09-16, choosing between three retention shapes:

    "Keep while the practice is open. On completion keep only the attempt they
     chose; delete the rest after 30 days."

WHY THIS IS A SWEEP AND NOT A SETTING. `retention_category` on a purge
dependency looked like the mechanism and is not: it applies only to rows whose
disposition is `retain`, and practice rows are `delete`. Nothing in the system
deleted practice attempts by AGE. The purge answers "this person asked to be
forgotten"; this answers "we said we would not keep this".

THE THREE THINGS IT MUST NEVER TAKE
  * an OPEN practice — the speaker is still using it;
  * the attempt they CHOSE — that is the one the promise keeps;
  * anything the Voice Album admitted. Album membership is Machine Yes + User
    Yes + Coach Yes about THE EXACT recording (L3). Delete the clip and the
    three-way agreement no longer refers to anything, which is worse than
    keeping it: the Album would still list it.

Audio first, row second, and never the row without the audio. A deleted row
whose file survives is the exact hole 0334 closed; doing it in that order
means a crash mid-sweep leaves a row we will revisit, not a file nobody can
find.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: The founder's number. Measured from when the practice closed, not from when
#: the attempt was recorded — the promise is about the practice being over.
RETENTION_DAYS = 30


def cutoff(now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
    return moment.isoformat()


def expired_attempts(practice: Any, attempts: Any, kept_by_album: Any) -> list[dict]:
    """The attempts this practice no longer promises to keep.

    Pure, so the rule can be read and tested without a database. Returns [] for
    anything it does not understand rather than guessing — a sweep that deletes
    on a misreading is worse than one that deletes nothing.
    """
    row: dict = practice if isinstance(practice, dict) else {}
    if row.get("status") == "open" or not row.get("status"):
        return []
    if not isinstance(attempts, list):
        return []
    chosen = str(row.get("selected_attempt_id") or "")
    protected = {str(item) for item in (kept_by_album or []) if item}
    out: list[dict] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_id = str(attempt.get("id") or "")
        if not attempt_id or attempt_id == chosen:
            continue
        if attempt.get("kept") is True or attempt_id in protected:
            continue
        out.append(attempt)
    return out


def sweep_practice_retention(
    *, database: Any, limit: int = 50, now: datetime | None = None,
) -> dict[str, int]:
    """Delete expired practice recordings. Returns a small tally for the log."""
    tally = {"practices": 0, "attempts": 0, "objects": 0, "failed": 0}
    try:
        practices = database.list_closed_practices_before(cutoff(now), limit) or []
    except Exception as error:
        logger.error("practice retention: could not list practices: %s", error)
        return tally

    for practice in practices:
        practice_id = str((practice or {}).get("id") or "")
        if not practice_id:
            continue
        tally["practices"] += 1
        try:
            attempts = database.list_confident_voice_practice_attempts(practice_id) or []
            protected = database.list_album_practice_attempt_ids(
                [str((row or {}).get("id") or "") for row in attempts
                 if isinstance(row, dict)]) or []
        except Exception as error:
            logger.error("practice retention: could not read %s: %s",
                         practice_id, error)
            tally["failed"] += 1
            continue
        for attempt in expired_attempts(practice, attempts, protected):
            if _expire(database, attempt, tally):
                tally["attempts"] += 1
            else:
                tally["failed"] += 1
    if tally["attempts"] or tally["failed"]:
        logger.info("practice retention swept %s", tally)
    return tally


def _expire(database: Any, attempt: dict, tally: dict[str, int]) -> bool:
    """One attempt: its recording, then its row. Never the row alone."""
    attempt_id = str(attempt.get("id") or "")
    try:
        removed = database.delete_practice_audio_object(attempt_id)
    except Exception as error:
        logger.error("practice retention: storage delete failed for %s: %s",
                     attempt_id, error)
        return False
    if removed is False:
        # The object is still out there. Leaving the row is the safer half of
        # the pair — it is what the next sweep will find it by.
        logger.warning(
            "practice retention: left attempt %s in place, its recording was "
            "not confirmed deleted", attempt_id)
        return False
    tally["objects"] += 1
    try:
        return bool(database.delete_confident_voice_practice_attempt(attempt_id))
    except Exception as error:
        logger.error("practice retention: row delete failed for %s: %s",
                     attempt_id, error)
        return False


# ── Withdrawal: turning practice off deletes it (founder 2026-09-25, E2) ──
#
# A different promise from the 30 days above, so different rules. That sweep
# keeps what the person chose and what the Voice Album admitted, because it
# answers "we said we would not keep this". A withdrawal answers "I no longer
# agree", and the approved confirm step says "Your practice recordings will be
# deleted", so here nothing is spared: open or closed, chosen or not, in the
# Album or not. An Album entry built on a practice clip goes with it
# (voice_album_practice CASCADE), which is what keeps the Album from listing a
# clip that no longer exists.
#
# The same order and the same caution as _expire: the recording first, then
# its row, and never the row while the recording may still exist. A practice
# row goes only once every attempt under it is gone.

WITHDRAWAL_RETRY_DAYS = 30


def erase_practice_for_principal(*, database: Any, principal_id: str) -> dict:
    """Delete every practice recording and row of one person.

    Returns {"practices", "attempts", "objects", "failed", "complete"}.
    `complete` is False while anything is left, so the caller can say so and
    the backstop sweep finds it again.
    """
    tally = {"practices": 0, "attempts": 0, "objects": 0, "failed": 0}
    try:
        practice_ids = database.practice_ids_for_principal(principal_id)
    except Exception as error:
        logger.error("practice withdrawal: could not resolve %s: %s",
                     principal_id, error)
        return {**tally, "failed": 1, "complete": False}
    for practice_id in practice_ids:
        try:
            attempts = database.list_confident_voice_practice_attempts(
                practice_id) or []
        except Exception as error:
            logger.error("practice withdrawal: could not read %s: %s",
                         practice_id, error)
            tally["failed"] += 1
            continue
        left = 0
        for attempt in attempts:
            if not isinstance(attempt, dict) or not attempt.get("id"):
                continue
            if _expire(database, attempt, tally):
                tally["attempts"] += 1
            else:
                tally["failed"] += 1
                left += 1
        if left:
            continue
        if database.delete_confident_voice_practice(practice_id):
            tally["practices"] += 1
        else:
            tally["failed"] += 1
    if tally["attempts"] or tally["failed"] or tally["practices"]:
        logger.info("practice withdrawal erased %s for %s", tally, principal_id)
    return {**tally, "complete": tally["failed"] == 0}


def sweep_withdrawn_practice(
    *, database: Any, limit: int = 20, now: datetime | None = None,
) -> dict[str, int]:
    """The backstop: finish any withdrawal whose erasure did not complete."""
    since = ((now or datetime.now(timezone.utc))
             - timedelta(days=WITHDRAWAL_RETRY_DAYS)).isoformat()
    totals = {"people": 0, "attempts": 0, "practices": 0, "failed": 0}
    try:
        principals = database.list_recent_practice_withdrawals(since, limit)
    except Exception as error:
        logger.error("practice withdrawal: could not list: %s", error)
        return totals
    for principal_id in principals:
        result = erase_practice_for_principal(
            database=database, principal_id=principal_id)
        totals["people"] += 1
        for key in ("attempts", "practices", "failed"):
            totals[key] += int(result.get(key) or 0)
    return totals
