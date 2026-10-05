"""The scheduled clean-up (founder 2026-10-05: decisions log N48.4 Q16 A,
"go with wave 3"; N45 Q3b and Q4; N46; retention schedule v1.0 §1).

Three rules, one definition of what is due. Migration 0423 decides it in SQL
(``retention_report_v1`` and the functions it reads), and three readers use
that and nothing else: scripts/retention_report.sql (the founder's read-only
report), a dry run and a live run. They cannot disagree about what is due,
because there is nothing for them to disagree about.

  1. An unclaimed guest older than 30 days is erased, recordings and all,
     by the account purge (services/data_purge.py) on a ``retention_expiry``
     request: the same inventory, byte-hash-verified object deletion,
     tombstones, retention rules and stops for review as any erasure. One
     that stopped for review is left for a person and not run again.
  2. Audio not used for 12 months is deleted with its voice measurements.
     One recording at a time: the claim empties the Take's measurement
     columns (in SQL), this module removes the measurement rows the reviewed
     lists below name, then deletes the object after matching its byte hash
     (services/lab_audio_storage.py, as the practice path does), and the
     settle records the deletion event naming this run. Measurements first:
     if anything fails after them the recording outlives its measurements,
     which the schedule allows, never the reverse (schedule §1).
  3. The five technical logs lose their rows older than 90 days, by id, in
     batches. A processing_jobs row that deletion evidence points at is
     kept: removing it would rewrite retained evidence.

TWO KEYS FOR A REAL RUN. A dry run (the default) counts what is due, logs it
by rule and writes a run record; it deletes nothing. A live run needs
``RETENTION_CLEANER_LIVE`` to be True -- the founder sets it in a reviewed
change after reading a dry run (N45: "the real run waits for the founder's
word") -- AND the caller to ask for ``mode="live"``. A live request while
the constant is False is refused; the run record says so and still counts,
as a dry run would.

RULE 1 IS A PURGE, so it also obeys the purge kill switch: a live run
erases guests only when the caller passes ``purge_execution=True``, which
the route takes from PHASE1_PURGE_EXECUTION_ENABLED -- the switch the
operator script (scripts/run_phase1_data_purge.py) and the deletion
completion run (services/deletion_completion.py) obey. Without it the
guests stay due and the record counts them under
``guests.held_purge_execution_off``; rules 2 and 3 are not purges and run.

Rows are removed here, through PostgREST, and only from relations named in
this file, as the account purge removes them: a migration may not carry a
row-removing statement (scripts/migrate.py refuses the file, and
MIGRATE_ON_BOOT would then hold back every later migration). The SQL side
selects, records, and empties columns.

AC-9: everything returned is a count about the system, never a person.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from postgrest.types import ReturnMethod

from services.data_purge_project_scope import orchestrator_for
from services.lab_audio_storage import (
    delete_verified_lab_audio_object,
    verify_lab_audio_object_absent,
)

logger = logging.getLogger(__name__)

#: THE FOUNDER'S KEY. False until the founder has read a dry run and sets it
#: in a reviewed change (decisions log N45, N48.4 Q16 A). While it is False a
#: live request is refused and recorded as refused, and nothing is deleted.
RETENTION_CLEANER_LIVE = False

CLEANER_VERSION = "retention-cleaner-v1"
DRY_RUN = "dry_run"
LIVE = "live"
MODES = (DRY_RUN, LIVE)
REFUSAL_LIVE_OFF = "RETENTION_CLEANER_LIVE_IS_OFF"

#: How much one live run takes on, so that a run started over HTTP ends in
#: minutes (a guest's erasure alone is a few hundred requests). What is left
#: is still due and the next day's run finds it; `left_due` says how much.
GUESTS_PER_RUN = 10
RECORDINGS_PER_RUN = 100
LOG_BATCH = 100
LOG_ROWS_PER_TABLE = 5_000

#: Rule 3: exactly the report's five tables (0423 retention_log_relations_v1).
LOG_TABLES: tuple[str, ...] = (
    "admin_annotations_log",
    "dev_bugs",
    "life_reminder_log",
    "mlc3_service_backpressure_events",
    "processing_jobs",
)

#: Rule 2: the voice-measurement rows removed with a recording (the `delete`
#: stores of 0423 retention_measurement_stores_v1). The `wipe` stores --
#: columns on rows whose words outlive the audio -- are emptied by the claim.
TAKE_MEASUREMENT_ROWS: tuple[tuple[str, str], ...] = (
    ("dimension_evaluations", "session_id"),
    ("session_sniper_metrics", "session_id"),
)
#: Aggregates over every recording of a speaker: they go with the account's
#: last live recording, when nothing they were made from is left.
ACCOUNT_MEASUREMENT_ROWS: tuple[tuple[str, str], ...] = (
    ("arc_part_acoustics", "user_id"),
    ("user_acoustic_baseline", "user_id"),
)

_MISSING_RELATION_CODES = frozenset({"42P01", "PGRST205"})
#: An error that is already a code, e.g. RETENTION_LOG_ROWS_REMAIN:dev_bugs.
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,80}(:[A-Za-z0-9_.]{1,79})?$")


def parse_mode(value: Any) -> str:
    """``dry_run`` unless the caller says ``live`` in so many words."""
    if value is None or value == "":
        return DRY_RUN
    mode = str(value).strip().lower()
    if mode not in MODES:
        raise ValueError(f"unknown mode {value!r}: use {DRY_RUN!r} or {LIVE!r}")
    return mode


def run(database: Any, *, mode: Any = DRY_RUN, as_of: str | None = None,
        purge_execution: bool = False) -> dict:
    """One run of the clean-up; returns its run record as counts.

    ``purge_execution`` is the purge kill switch, for rule 1 of a live run.
    ``as_of`` is for tests: the database refuses a moment in the future, and
    an earlier one can only select a subset of what is due today.
    """
    mode = parse_mode(mode)
    if mode == LIVE and RETENTION_CLEANER_LIVE is True:
        return _live(database, as_of=as_of,
                     purge_execution=purge_execution is True)
    refusal = REFUSAL_LIVE_OFF if mode == LIVE else None
    record = _rpc(database, "record_retention_dry_run_v1", {
        "p_requested_mode": mode, "p_cleaner_version": CLEANER_VERSION,
        "p_refusal": refusal, "p_as_of": as_of,
    })
    summary = _summary(record)
    _log(summary)
    return summary


def _live(database: Any, *, as_of: str | None, purge_execution: bool) -> dict:
    record = _rpc(database, "begin_retention_live_run_v1", {
        "p_cleaner_version": CLEANER_VERSION, "p_as_of": as_of,
    })
    run_id = str(record.get("id") or "")
    if not run_id:
        raise RuntimeError("RETENTION_RUN_NOT_STARTED")
    state, error_code = "completed", None
    try:
        _registry_matches(database)
        _erase_guests(database, run_id, purge_execution=purge_execution)
        _delete_recordings(database, run_id)
        _delete_log_rows(database, run_id)
    except Exception as error:
        logger.error("retention cleaner: live run %s stopped: %s", run_id,
                     error, exc_info=True)
        state, error_code = "failed", _code(error)
    finished = _rpc(database, "finish_retention_live_run_v1", {
        "p_run_id": run_id, "p_state": state, "p_error_code": error_code,
    })
    summary = _summary(finished)
    _log(summary)
    return summary


def _registry_matches(database: Any) -> None:
    """Rows go only from the stores the migration names. If this file and
    the database ever disagree about them, nothing is deleted."""
    stores = _rows(database, "retention_measurement_stores_v1", {})
    named = {
        (str(s.get("relation")), str(s.get("key_column")), str(s.get("scope")))
        for s in stores if s.get("action") == "delete"
    }
    expected = (
        {(r, c, "take") for r, c in TAKE_MEASUREMENT_ROWS}
        | {(r, c, "account") for r, c in ACCOUNT_MEASUREMENT_ROWS}
    )
    logs = {str(r.get("relation")) for r in
            _rows(database, "retention_log_relations_v1", {})}
    if named != expected or logs != set(LOG_TABLES):
        raise RuntimeError("RETENTION_REGISTRY_MISMATCH")


# ── Rule 1: unclaimed guests ───────────────────────────────────────────────

def _erase_guests(database: Any, run_id: str, *, purge_execution: bool) -> None:
    due = _due(database, run_id, "guests", limit=GUESTS_PER_RUN)
    if due and not purge_execution:
        # The purge kill switch is off: no request is opened, nothing is
        # erased, and these guests are still due for a run with it on.
        _count(database, run_id, "guests.held_purge_execution_off", len(due))
        return
    for principal_id in due:
        outcome = _erase_guest(database, run_id, principal_id)
        _count(database, run_id, f"guests.{outcome}")


def _erase_guest(database: Any, run_id: str, principal_id: str) -> str:
    receipt = _rpc(database, "request_retention_guest_purge_v1", {
        "p_run_id": run_id, "p_principal_id": principal_id,
    })
    if receipt.get("skipped"):
        return f"skipped_{receipt['skipped']}"
    request_id = str(receipt.get("purge_request_id") or "")
    if not request_id:
        raise RuntimeError("RETENTION_PURGE_NOT_REQUESTED")
    if receipt.get("state") == "done":
        return "erased"
    try:
        outcome = orchestrator_for(database, request_id).run(request_id)
    except Exception as error:
        logger.error("retention cleaner: erasure %s of an unclaimed guest "
                     "stopped: %s", request_id, error, exc_info=True)
        return "failed"
    state = str(((outcome or {}).get("result") or {}).get("state") or "")
    return {"done": "erased", "review_required": "review_required"}.get(
        state, "failed")


# ── Rule 2: recordings and their voice measurements ────────────────────────

def _delete_recordings(database: Any, run_id: str) -> None:
    for audio_id in _due(database, run_id, "audio", limit=RECORDINGS_PER_RUN):
        _delete_recording(database, run_id, audio_id)


def _delete_recording(database: Any, run_id: str, audio_id: str) -> str:
    """One recording: measurements first, then the object, then the event."""
    claim = _rpc(database, "claim_retention_audio_v1", {
        "p_run_id": run_id, "p_audio_object_id": audio_id,
    })
    if claim.get("skipped"):
        return str(claim["skipped"])
    error_code = None
    try:
        _delete_measurement_rows(database, run_id, claim)
        outcome = _delete_object(claim)
    except Exception as error:
        logger.warning("retention cleaner: recording %s kept: %s", audio_id,
                       error, exc_info=True)
        outcome, error_code = "failed", _code(error)
    _rpc(database, "settle_retention_audio_v1", {
        "p_run_id": run_id, "p_audio_object_id": audio_id,
        "p_outcome": outcome, "p_error_code": error_code,
    })
    return outcome


def _delete_measurement_rows(database: Any, run_id: str,
                             claim: Mapping[str, Any]) -> None:
    take_id = str(claim.get("take_id") or "")
    if not take_id:
        raise RuntimeError("RETENTION_CLAIM_WITHOUT_TAKE")
    for relation, column in TAKE_MEASUREMENT_ROWS:
        _remove_rows(database, run_id, relation, column, take_id)
    user_id = str(claim.get("account_user_id") or "")
    if claim.get("last_audio_of_account") is True and user_id:
        for relation, column in ACCOUNT_MEASUREMENT_ROWS:
            _remove_rows(database, run_id, relation, column, user_id)


def _remove_rows(database: Any, run_id: str, relation: str, column: str,
                 value: str) -> int:
    """Every row of one measurement store under this key, or an error."""
    try:
        removed = (database.client.table(relation).delete()
                   .eq(column, value).execute().data or [])
        left = (database.client.table(relation).select(column)
                .eq(column, value).limit(1).execute().data or [])
    except Exception as error:
        if _missing_relation(error):
            return 0  # a database without this store holds none of it
        raise
    if left:
        raise RuntimeError(f"RETENTION_MEASUREMENT_ROWS_REMAIN:{relation}")
    if removed:
        _count(database, run_id, f"measurements.{relation}", len(removed))
    return len(removed)


def _delete_object(claim: Mapping[str, Any]) -> str:
    """The recording's bytes, matched to the registry's hash before they go."""
    key = str(claim.get("object_key") or "")
    bucket = str(claim.get("bucket") or "")
    provider = str(claim.get("storage_provider") or "")
    try:
        deleted = delete_verified_lab_audio_object(
            key, bucket=bucket, storage_provider=provider,
            expected_sha256=str(claim.get("exact_bytes_sha256") or ""))
    except Exception:
        # An object an earlier run removed before it could record so is
        # gone, and that is verified here, never assumed. Anything else --
        # a different object at that key, a provider error -- stands.
        if verify_lab_audio_object_absent(key, bucket=bucket,
                                          storage_provider=provider):
            return "already_absent"
        raise
    if not deleted:
        raise RuntimeError("RETENTION_OBJECT_DELETION_NOT_VERIFIED")
    return "deleted"


# ── Rule 3: the five technical logs ─────────────────────────────────────────

def _delete_log_rows(database: Any, run_id: str) -> None:
    for table in LOG_TABLES:
        try:
            _empty_log(database, run_id, table)
        except Exception as error:
            logger.error("retention cleaner: %s rows kept: %s", table, error,
                         exc_info=True)
            _count(database, run_id, f"logs.{table}.failed")


def _empty_log(database: Any, run_id: str, table: str) -> None:
    removed = 0
    batch = _due(database, run_id, "logs", relation=table, limit=LOG_BATCH)
    while batch and removed < LOG_ROWS_PER_TABLE:
        (database.client.table(table).delete(returning=ReturnMethod.minimal)
         .in_("id", batch).execute())
        following = _due(database, run_id, "logs", relation=table,
                         limit=LOG_BATCH)
        if set(batch) & set(following):
            raise RuntimeError(f"RETENTION_LOG_ROWS_REMAIN:{table}")
        _count(database, run_id, f"logs.{table}", len(batch))
        removed += len(batch)
        batch = following


# ── Plumbing ────────────────────────────────────────────────────────────────

def _due(database: Any, run_id: str, rule: str, *, limit: int,
         relation: str | None = None) -> list[str]:
    rows = _rows(database, "list_retention_due_v1", {
        "p_run_id": run_id, "p_rule": rule, "p_relation": relation,
        "p_limit": int(limit),
    })
    return [str(row["item_id"]) for row in rows if row.get("item_id")]


def _count(database: Any, run_id: str, key: str, n: int = 1) -> None:
    _rpc(database, "count_retention_outcome_v1", {
        "p_run_id": run_id, "p_key": key, "p_n": int(n),
    })


def _rpc(database: Any, name: str, params: Mapping[str, Any]) -> dict:
    data = database.client.rpc(name, dict(params)).execute().data
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        raise RuntimeError(f"RETENTION_RPC_EMPTY:{name}")
    return data


def _rows(database: Any, name: str, params: Mapping[str, Any]) -> list[dict]:
    data = database.client.rpc(name, dict(params)).execute().data
    if isinstance(data, dict):
        return [data]
    return [row for row in (data or []) if isinstance(row, dict)]


def _missing_relation(error: BaseException) -> bool:
    code = str(getattr(error, "code", "") or getattr(error, "pgcode", "") or "")
    return code in _MISSING_RELATION_CODES


def _code(error: BaseException) -> str:
    code = str(getattr(error, "code", "") or "")
    if code:
        return code[:160]
    text = str(error)
    return text if _CODE.match(text) else type(error).__name__


def _summary(record: Mapping[str, Any]) -> dict:
    return {
        "run_id": str(record.get("id") or ""),
        "requested_mode": record.get("requested_mode"),
        "mode": record.get("mode"),
        "state": record.get("state"),
        "refusal": record.get("refusal"),
        "as_of": record.get("as_of"),
        "cleaner_version": record.get("cleaner_version"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "due": list(record.get("due") or []),
        "done": dict(record.get("done") or {}),
        "left_due": record.get("left_due"),
        "error_code": record.get("error_code"),
    }


def _log(summary: Mapping[str, Any]) -> None:
    logger.info("retention cleaner: %s run %s %s, as of %s",
                summary.get("mode"), summary.get("run_id"),
                summary.get("state"), summary.get("as_of"))
    if summary.get("refusal"):
        logger.warning("retention cleaner: a live run was asked for and "
                       "refused (%s); this run only counted",
                       summary.get("refusal"))
    for line in summary.get("due") or []:
        logger.info("retention cleaner: rule %s · %s · %s", line.get("rule"),
                    line.get("would_delete"), line.get("how_many"))
    if summary.get("done"):
        logger.info("retention cleaner: done %s", summary.get("done"))
