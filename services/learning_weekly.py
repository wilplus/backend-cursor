"""The weekly learning job (founder 2026-09-30, L4, L5; build plan ML-3).

Once a week, poked by a Railway cron through a shared secret:

  1. the ledger is read (services.learning_ledger) and written as one
     snapshot row for the ISO week; a second fire in the same week replaces
     the row, so the cron may double-fire without writing twice;
  2. the shadow cues are checked against their bar; for every cue that
     cleared it, the migration text a promotion would merge is drafted and
     stored beside the snapshot. The job never promotes: merging the
     drafted file after the founder's go is the promotion (ML-14);
  3. pairs are exported per surface ONLY where the dataset-release door is
     open AND the founder named the surface (services/pair_release.py);
     before that the consent refresh and the voided-release sweep run
     (services/pair_consent.py, ML-8). Both are code constants: door 2 is
     open since 2026-10-01 for exercise_script, praise_line and
     clearer_version (N16, N18); every other surface, and any surface
     while the bucket or the signing key is missing, exports nothing and
     its row says why. Each pair is re-decided at release time (PLF-P5);
  4. the drift run (PM-3, services/drift_job.py: PSI on the inputs, the
     p-chart on the decisions, the 2x2 per dimension) is stored with the
     week, so the research screen's drift panel reads a real week (ML-7).
     Its only write is minting the frozen reference the first time there
     is enough data, which the table refuses to overwrite; a separate drift
     cron, if one runs too, mints nothing twice.

Nothing here trains, promotes, or flips a door. Counts about the system,
never about a person (AC-9 for everyone but the founder's own pages).
"""
from __future__ import annotations

from pathlib import Path

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

_log = logging.getLogger(__name__)

JOB_VERSION = "learning-weekly-v1"
#: Where a drafted promotion migration would live (a repo path, not an object key).
MIGRATIONS_DIR = "migrations"


def week_start(now: Optional[datetime] = None) -> date:
    """The Monday of the ISO week `now` falls in (UTC)."""
    moment = now or datetime.now(timezone.utc)
    day = moment.date()
    return day - timedelta(days=day.weekday())


def migration_draft(cue: str, *, next_number: str = "NNNN") -> dict:
    """The migration a promotion would merge: the one UPDATE that flips a
    shadow cue to detected, in the house shape (idempotent, no env var).
    Returned as text for the founder's page; nothing is written to disk."""
    slug = f"{cue}_is_detected"
    from services.acoustic_cues import CUES as ACOUSTIC_CUES
    detector = "acoustic_cues" if cue in ACOUSTIC_CUES else "verbal_cues"
    sql = (
        f"-- {cue} is detected (the weekly learning job read it READY; founder go\n"
        f"-- merges this file, which IS the promotion: ML-14). Idempotent.\n"
        "BEGIN;\n"
        "UPDATE public.speaking_error\n"
        "   SET status = 'detected', updated_at = now()\n"
        f" WHERE error_id = '{cue}' AND status = 'shadow'\n"
        f"   AND detector_ref = '{detector}:{cue}';\n"
        "COMMIT;\n"
    )
    return {"cue": cue, "file": str(Path(MIGRATIONS_DIR) / f"{slug}.sql"),
            "manifest_line": f"{next_number}\t{slug}.sql", "sql": sql}


def run_weekly(database: Any, *, config: Any = None,
               now: Optional[datetime] = None, provider: Any = None) -> dict:
    """The job. Returns what it wrote, for the cron's log and the founder's
    page. Raises only when the ledger itself cannot be read."""
    from services.learning_ledger import ledger as read_ledger
    if config is None:
        from config import Config
        config = Config()
    from services.pair_consent import refresh
    from services.pair_release import R2ReleaseStorage, sweep_voided
    moment = now or datetime.now(timezone.utc)
    # Door 1's weekly pass first (ML-8): every pair's releasability from the
    # consent ledger, and the voiding of releases whose owner withdrew. Then
    # the ledger reads the counts as they stand.
    consent = refresh(database)
    snapshot = read_ledger(database, config=config)
    ready = [cue for cue, row in (snapshot.get("shadow_cues") or {}).items()
             if isinstance(row, dict) and row.get("ready")]
    drafts = {cue: migration_draft(cue) for cue in ready}
    storage = R2ReleaseStorage(config)
    exported = _export_pairs(database, snapshot, config,
                             week_start_day=week_start(moment), storage=storage)
    # Revocation purges the copies, whatever the door says (ML-8).
    swept = sweep_voided(database, storage)
    # Door 3's weekly pass (ML-11): the withdrawal sweep at the provider,
    # the poll of running jobs (a finished one is evaluated), and a start
    # where the door, the founder's sentence, the sealed golden set and 200
    # trainable pairs all hold. Closed today: every surface says why.
    training = _training_pass(database, config, now=moment, provider=provider)
    snapshot["doors_pass"] = {"consent_refresh": consent, "release_sweep": swept,
                              "training": training}
    # The week's PSI 2x2 (ML-7: the research screen's drift panel).
    drift = _drift_pass(database)
    snapshot["drift"] = drift
    row = {
        "week_start": week_start(moment).isoformat(),
        "ledger_version": str(snapshot.get("ledger_version") or ""),
        "snapshot": snapshot,
        "ready_cues": ready,
        "migration_drafts": drafts,
        "exported": exported,
        "updated_at": moment.isoformat(),
    }
    stored = database.upsert_ledger_snapshot(**row)
    return {
        "job_version": JOB_VERSION,
        "week_start": row["week_start"],
        "stored": isinstance(stored, dict),
        "ready_cues": ready,
        "migration_drafts": drafts,
        "exported": exported,
        "consent_refresh": consent,
        "release_sweep": swept,
        "training": training,
        "drift": {"worst": drift.get("worst"), "minted": drift.get("minted"),
                  "note": drift.get("note") or drift.get("unavailable")},
        "unavailable": list(snapshot.get("unavailable") or []),
        "doors": snapshot.get("doors"),
    }


def _export_pairs(database: Any, snapshot: dict, config: Any,
                  *, week_start_day: Optional[date] = None,
                  storage: Any = None) -> list[dict]:
    """Per surface: the release, or the reason it stayed. The door is a code
    constant and each surface needs the founder's sentence (ML-9); while
    either is missing the row says so in words."""
    from services.pair_release import R2ReleaseStorage, export_surface, why_not
    out = []
    for surface in (snapshot.get("pairs") or {}):
        reason = why_not(config, surface)
        if reason:
            waiting = int(((snapshot.get("pairs") or {}).get(surface) or {}).get("unexported") or 0)
            out.append({"surface": surface, "exported": 0, "waiting": waiting, "why": reason})
            continue
        try:
            out.append(export_surface(
                database, storage or R2ReleaseStorage(config), surface=surface,
                week_start=week_start_day or week_start(), config=config))
        except Exception as e:  # noqa: BLE001 -- named, never a silent zero
            _log.warning("pair release failed surface=%s: %s", surface, e, exc_info=True)
            out.append({"surface": surface, "exported": 0, "waiting": None,
                        "why": f"export failed: {str(e)[:120]}"})
    return out


def _drift_pass(database: Any) -> dict:
    """The weekly PSI 2x2 (PM-3), for the week's row. The drift run never
    raises by design; anything else is named, never a reason the snapshot
    is not written. PIPELINE_CHANGED and UPSTREAM_CHANGE are logged at
    WARNING, as the drift webhook logs them."""
    from services import drift_job
    try:
        report = drift_job.run_weekly(weeks=drift_job.REFERENCE_WEEKS, database=database)
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("drift pass failed: %s", e, exc_info=True)
        return {"unavailable": str(e)[:200]}
    if report.get("worst") in ("PIPELINE_CHANGED", "UPSTREAM_CHANGE"):
        _log.warning("drift: %s (weekly learning job)", report.get("worst"))
    return report


def _training_pass(database: Any, config: Any, *, now: Optional[datetime],
                   provider: Any = None) -> dict:
    """Door 3's step, never a reason the snapshot is not written."""
    from services.model_training import run_training_pass
    try:
        return run_training_pass(database, config=config, provider=provider, now=now)
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("training pass failed: %s", e, exc_info=True)
        return {"unavailable": str(e)[:200]}
