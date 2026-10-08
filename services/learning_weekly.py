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
     cron, if one runs too, mints nothing twice;

  5. every standing door 2 release is read back and checked, and a capped
     number of the confidence chain's R2 objects are downloaded and
     checked; each check appends one verification row the database judges
     (F-8, ``services/object_verification.py``);

  6. the MLC-2 foundation's aggregate health is read and kept beside the
     doors (F-9, ``get_mlc2_foundation_health_v1``), after the checks so
     its count of unverified objects is this week's: pending and failed
     outbox events, principals without a speaker, objects without a
     verification, open purge requests, and the three hard-off learning
     capabilities. Nothing calls it otherwise; this weekly row is where the
     founder reads it.

  7. while ``DETECTOR_TRAINING_AUTHORISED`` is on (3.5 pack, file 22 E3),
     the learned detectors are fitted on our own systems from the blind-check
     answers of speakers who hold the training yes and have not objected,
     and their verdicts go to the shadow log only
     (``services/detector_candidates.fit_all``). Off, the step reads nothing.

Nothing here promotes or flips a door, and nothing trains but step 7's
shadow-only detector fit. Counts about the system,
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
    # F-8: every standing release read back and checked, and a capped
    # number of chain objects downloaded and checked; each check is one
    # append-only row the database judges.
    verifications = _verification_pass(database, storage, config, exported)
    # Door 3's weekly pass (ML-11): the withdrawal sweep at the provider,
    # the poll of running jobs (a finished one is evaluated), and a start
    # where the door, the founder's sentence, the sealed golden set and 200
    # trainable pairs all hold. Closed today: every surface says why.
    training = _training_pass(database, config, now=moment, provider=provider)
    # 3.5 E3: the learned detectors, fitted only while
    # DETECTOR_TRAINING_AUTHORISED is on, on consented answers, into the
    # shadow log only. Off, it reads nothing.
    detector_fit = _detector_fit_pass(database, config, now=moment)
    foundation = foundation_health(database)
    snapshot["doors_pass"] = {"consent_refresh": consent, "release_sweep": swept,
                              "training": training, "detector_fit": detector_fit}
    # The week's PSI 2x2 (ML-7: the research screen's drift panel).
    drift = _drift_pass(database)
    snapshot["drift"] = drift
    snapshot["foundation_health"] = foundation
    snapshot["verifications"] = verifications
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
        "detector_fit": detector_fit,
        "drift": {"worst": drift.get("worst"), "minted": drift.get("minted"),
                  "note": drift.get("note") or drift.get("unavailable")},
        "foundation_health": foundation,
        "verifications": verifications,
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


def _detector_fit_pass(database: Any, config: Any, *, now: Optional[datetime]) -> dict:
    """The learned detectors' weekly fit (``detector_candidates.fit_all``),
    never a reason the snapshot is not written."""
    from services.detector_candidates import fit_all
    try:
        return fit_all(database, config=config, now=now)
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("detector fit pass failed: %s", e, exc_info=True)
        return {"unavailable": str(e)[:200]}


def _verification_pass(database: Any, storage: Any, config: Any,
                       exported: Optional[list] = None) -> dict:
    """F-8's weekly step (services/object_verification.py): the releases
    this run's export just wrote are read back (each exported row gains
    ``verified``), then every other standing release and a capped number of
    chain objects are checked. Never a reason the snapshot is not written."""
    from services.object_verification import (
        check_chain_objects, check_pair_releases, read_back_exports,
    )
    read_back: set = set()
    try:
        read_back = read_back_exports(database, storage, config, exported or [])
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("release read-back failed: %s", e, exc_info=True)
    out: dict = {"read_back": len(read_back)}
    for name, step in (("pair_releases",
                        lambda: check_pair_releases(database, storage, config,
                                                    skip=read_back)),
                       ("chain_objects", lambda: check_chain_objects(database))):
        try:
            out[name] = step()
        except Exception as e:  # noqa: BLE001 -- named, never a silent zero
            _log.warning("verification pass %s failed: %s", name, e, exc_info=True)
            out[name] = {"unavailable": str(e)[:200]}
    return out


#: What the weekly row keeps of the foundation's health: aggregate counts and
#: the three hard-off flags, never an id, a recording or a word (AC-9).
FOUNDATION_HEALTH_KEYS = (
    "generated_at", "pending_outbox_count", "failed_outbox_count",
    "oldest_pending_outbox_at", "unresolved_principal_count",
    "unverified_object_count", "pending_purge_count",
    "dataset_creation_enabled", "training_enabled", "promotion_enabled",
)


def foundation_health(database: Any) -> dict:
    """F-9: ``get_mlc2_foundation_health_v1``, aggregate only. Never a reason
    the snapshot is not written; a failure is named."""
    reader = getattr(database, "get_mlc2_foundation_health", None)
    if reader is None:
        return {"unavailable": "no foundation health on this database"}
    try:
        health = reader() or {}
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("foundation health read failed: %s", e, exc_info=True)
        return {"unavailable": str(e)[:200]}
    out = {key: health.get(key) for key in FOUNDATION_HEALTH_KEYS if key in health}
    # The capabilities are hard-off in SQL; anything else is a fault to see.
    out["learning_capabilities_closed"] = all(
        health.get(key) is False for key in
        ("dataset_creation_enabled", "training_enabled", "promotion_enabled"))
    return out
