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
     open. The door is a code constant, closed today, so the job exports
     nothing and says so.

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
    sql = (
        f"-- {cue} is detected (the weekly learning job read it READY; founder go\n"
        f"-- merges this file, which IS the promotion: ML-14). Idempotent.\n"
        "BEGIN;\n"
        "UPDATE public.speaking_error\n"
        "   SET status = 'detected', updated_at = now()\n"
        f" WHERE error_id = '{cue}' AND status = 'shadow'\n"
        f"   AND detector_ref = 'verbal_cues:{cue}';\n"
        "COMMIT;\n"
    )
    return {"cue": cue, "file": str(Path(MIGRATIONS_DIR) / f"{slug}.sql"),
            "manifest_line": f"{next_number}\t{slug}.sql", "sql": sql}


def run_weekly(database: Any, *, config: Any = None,
               now: Optional[datetime] = None) -> dict:
    """The job. Returns what it wrote, for the cron's log and the founder's
    page. Raises only when the ledger itself cannot be read."""
    from services.learning_ledger import ledger as read_ledger
    if config is None:
        from config import Config
        config = Config()
    moment = now or datetime.now(timezone.utc)
    snapshot = read_ledger(database, config=config)
    ready = [cue for cue, row in (snapshot.get("shadow_cues") or {}).items()
             if isinstance(row, dict) and row.get("ready")]
    drafts = {cue: migration_draft(cue) for cue in ready}
    exported = _export_pairs(database, snapshot, config)
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
        "unavailable": list(snapshot.get("unavailable") or []),
        "doors": snapshot.get("doors"),
    }


def _export_pairs(database: Any, snapshot: dict, config: Any) -> list[dict]:
    """Per surface: exported when door 2 is open, else the reason. The door
    is one code constant for every surface today (ML-9 opens it per surface
    by a reviewed change carrying the founder's sentence)."""
    door_open = bool(getattr(config, "MLC2_DATASET_RELEASES_ENABLED", False))
    out = []
    for surface, entry in (snapshot.get("pairs") or {}).items():
        waiting = int((entry or {}).get("unexported") or 0)
        if not door_open:
            out.append({"surface": surface, "exported": 0, "waiting": waiting,
                        "why": "door 2 closed (MLC2_DATASET_RELEASES_ENABLED)"})
            continue
        # The door is open by a reviewed change; the export itself is ML-9's
        # signed manifest and JSONL to the bucket. Until it lands the job
        # names the gap rather than pretending.
        out.append({"surface": surface, "exported": 0, "waiting": waiting,
                    "why": "exporter not built (ML-9)"})
    return out
