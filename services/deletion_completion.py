"""Deletions that complete by themselves (founder 2026-10-05, decisions log
N48.4: Q14 A, Q17 A; PLF-T4, L5; migration 0422).

Poked by a Railway cron through POST /v2/internal/deletion/complete-due
(bin/railway-deletion-completion-cron.sh). For every request whose seven
days have passed, oldest first:

  * an account deletion is started (``start_due_account_deletion_v1``: the
    purge request and the permanent block), its purge is run by the
    existing orchestrator (freeze -> resolve -> finalize), and a purge that
    finalized 'done' marks the request done on verified terminal evidence
    (``complete_phase1_account_deletion_v1``);
  * a project deletion is confirmed by the system
    (``start_due_project_deletion_v1``) and its one-project purge is run;
    the project orchestrator marks the project request done itself.

A purge that stops on rows no rule decides finalizes 'review_required'. The
orchestrator deletes nothing when any target is unknown, so nothing is ever
deleted past a refusal. Such a request is LEFT FOR A PERSON: it is never
run again here, it is logged once with the targets that stopped it, and
every run lists it under ``left_for_a_person`` (and GET
/v2/admin/deletions shows it).

TWO GATES. The route needs its secret. Executing needs
``PHASE1_PURGE_EXECUTION_ENABLED``, the operator script's kill switch;
without it the run is a dry run that reads what is due and writes nothing.

ONE RUN AT A TIME (``deletion_completion_lease``). Safe to repeat: a started
request resumes, a finished purge is never run again (its finalize would
write a second 'completed' event), and a request left for a person is not
retried.

THE RELEASED COPIES (0454). An erasure request voids every pair release
holding one of its pairs at once. A run that executes ends by sweeping the
voided releases (services/pair_release.py), so their objects go within the
hour rather than only at the weekly learning job; a sweep that cannot run
is reported and never fails the run.

AC-9: internal. The report carries ids, states and reason codes, never
anyone's words or audio, and is never proxied to a speaker.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

JOB_VERSION = "deletion-completion-v1"
LEASE_SECONDS = 1800
DEFAULT_LIMIT = 10
MAX_LIMIT = 20
#: A purge in these states may be (re)run: nothing has finalized it yet.
RUNNABLE = ("requested", "in_progress")
#: Fresh starts first, then bookkeeping, then resumptions: a request that
#: fails on every run cannot hold back one whose seven days just ended.
_ORDER = {"start": 0, "complete": 1, "resume": 2, "review": 3}
_REASONS_SHOWN = 50
_ACCOUNT_COLUMNS = "id,state,completes_after,purge_request_id"
_PROJECT_COLUMNS = "id,project_id,state,due_at,purge_request_id"


@dataclass(frozen=True)
class Work:
    kind: str                 # "account" | "project"
    request_id: str
    action: str               # "start" | "resume" | "complete" | "review"
    due_at: str
    purge_request_id: Optional[str] = None
    project_id: Optional[str] = None

    def view(self) -> dict:
        return {"kind": self.kind, "request_id": self.request_id,
                "action": self.action, "due_at": self.due_at,
                "purge_request_id": self.purge_request_id,
                "project_id": self.project_id}


def _at(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _code(error: BaseException) -> str:
    return (str(getattr(error, "code", "") or "") or str(error)[:120]
            or type(error).__name__)


def _scalar(data: Any) -> Any:
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict) and len(data) == 1:
        data = next(iter(data.values()))
    return data


def _row(data: Any) -> dict:
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError("DELETION_COMPLETION_EMPTY_ROW")
    return data


def _select(client: Any, relation: str, columns: str, state: str) -> list[dict]:
    return [row for row in (
        client.table(relation).select(columns).eq("state", state)
        .limit(500).execute().data or []
    ) if isinstance(row, dict)]


def _purge_states(client: Any, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (client.table("data_purge_requests").select("id,state")
            .in_("id", sorted(set(ids))).execute().data or [])
    return {str(r["id"]): str(r.get("state") or "") for r in rows
            if isinstance(r, dict) and r.get("id")}


def _due(rows: list[dict], key: str, now: datetime) -> list[dict]:
    out = []
    for row in rows:
        ends = _at(row.get(key))
        if ends is not None and ends <= now:
            out.append(row)
    return out


def _after_start(kind: str, row: dict, state: str, key: str,
                 now: datetime) -> Optional[Work]:
    """A started (account) or confirmed (project) request, by its purge.

    A purge is never run before its request's seven days are over, even one
    an operator confirmed early or one carried over from before 0422: the
    window is the promise; an operator who wants it sooner runs the script.
    """
    if state in RUNNABLE:
        ends = _at(row.get(key))
        if ends is None or ends > now:
            return None
    action = ("complete" if state == "done"
              else "resume" if state in RUNNABLE else "review")
    return Work(kind, str(row["id"]), action, str(row.get(key) or ""),
                str(row.get("purge_request_id") or "") or None,
                str(row.get("project_id") or "") or None)


def collect(database: Any, now: Optional[datetime] = None) -> list[Work]:
    """Everything due, oldest first: requests past their seven days to
    start, started ones to resume or mark done, and the ones a person must
    look at (action 'review'). Reads only."""
    client = database.client
    moment = now or datetime.now(timezone.utc)
    work: list[Work] = []
    for row in _due(_select(client, "account_deletion_requests",
                            _ACCOUNT_COLUMNS, "pending"), "completes_after", moment):
        work.append(Work("account", str(row["id"]), "start",
                         str(row.get("completes_after") or "")))
    for row in _due(_select(client, "project_deletion_requests",
                            _PROJECT_COLUMNS, "pending"), "due_at", moment):
        work.append(Work("project", str(row["id"]), "start",
                         str(row.get("due_at") or ""), None,
                         str(row.get("project_id") or "") or None))
    started = _select(client, "account_deletion_requests", _ACCOUNT_COLUMNS, "started")
    confirmed = _select(client, "project_deletion_requests", _PROJECT_COLUMNS, "confirmed")
    states = _purge_states(client, [
        str(r["purge_request_id"]) for r in started + confirmed
        if r.get("purge_request_id")])
    for kind, rows, key in (("account", started, "completes_after"),
                            ("project", confirmed, "due_at")):
        for row in rows:
            state = states.get(str(row.get("purge_request_id") or ""), "")
            item = _after_start(kind, row, state, key, moment)
            if item is not None:
                work.append(item)
    work.sort(key=lambda item: (_ORDER[item.action], item.due_at, item.kind,
                                item.request_id))
    return work


def review_reasons(database: Any, purge_request_id: Optional[str]) -> list[dict]:
    """The targets that stopped a purge: what a person must decide."""
    if not purge_request_id:
        return []
    rows = (database.client.table("data_purge_targets")
            .select("target_ref,state,metadata,last_error_code")
            .eq("purge_request_id", purge_request_id)
            .in_("state", ["unknown", "failed"])
            .limit(_REASONS_SHOWN).execute().data or [])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("metadata")
        metadata: dict = raw if isinstance(raw, dict) else {}
        out.append({
            "target_ref": str(row.get("target_ref") or ""),
            "state": str(row.get("state") or ""),
            "reason": str(metadata.get("reason_code")
                          or row.get("last_error_code")
                          or metadata.get("error_code") or ""),
        })
    return sorted(out, key=lambda item: item["target_ref"])


def _lease(client: Any, name: str, params: dict) -> bool:
    return _scalar(client.rpc(name, params).execute().data) is True


def _start(database: Any, work: Work) -> str:
    if work.kind == "account":
        row = _row(database.client.rpc("start_due_account_deletion_v1", {
            "p_request_id": work.request_id}).execute().data)
    else:
        from services.project_deletion import ProjectDeletionService

        row = ProjectDeletionService(database).start_due(work.request_id)
    purge = str(row.get("purge_request_id") or "")
    if not purge:
        raise RuntimeError("DELETION_START_WITHOUT_PURGE")
    return purge


def _finish(database: Any, work: Work) -> None:
    """Mark the request done; the database checks the evidence."""
    if work.kind == "account":
        _row(database.client.rpc("complete_phase1_account_deletion_v1", {
            "p_request_id": work.request_id}).execute().data)
    else:
        _row(database.client.rpc("complete_project_deletion_v1", {
            "p_purge_request_id": work.purge_request_id}).execute().data)


def _execute(database: Any, work: Work) -> dict:
    from services.data_purge_project_scope import orchestrator_for

    purge = work.purge_request_id
    state = "done" if work.action == "complete" else ""
    if work.action == "start":
        purge = _start(database, work)
    if work.action in ("start", "resume"):
        run = orchestrator_for(database, str(purge)).run(str(purge))
        state = str((run.get("result") or {}).get("state") or "")
    done = Work(work.kind, work.request_id, work.action, work.due_at,
                purge, work.project_id)
    if state == "done":
        _finish(database, done)
        return {"purge_request_id": purge, "result": "completed"}
    if state == "review_required":
        reasons = review_reasons(database, purge)
        logger.warning(
            "deletion left for a person kind=%s request=%s purge=%s reasons=%s",
            work.kind, work.request_id, purge,
            sorted({r["reason"] for r in reasons}))
        return {"purge_request_id": purge, "result": "left_for_a_person",
                "reasons": reasons}
    return {"purge_request_id": purge, "result": state or "unknown"}


def _handle(database: Any, work: Work, *, execute: bool) -> dict:
    outcome = work.view()
    if not execute:
        outcome["result"] = f"would_{work.action}"
        return outcome
    try:
        outcome.update(_execute(database, work))
    except Exception as error:
        logger.error("deletion completion failed kind=%s request=%s: %s",
                     work.kind, work.request_id, error, exc_info=True)
        outcome.update(result="error", error_code=_code(error))
    return outcome


def _sweep_releases(database: Any, storage: Any = None) -> dict:
    """Delete the objects of voided pair releases and mark them purged."""
    from services.pair_release import R2ReleaseStorage, sweep_voided

    try:
        if storage is None:
            from config import Config

            storage = R2ReleaseStorage(Config())
        return sweep_voided(database, storage)
    except Exception as error:  # noqa: BLE001 -- reported, the weekly sweep retries
        logger.warning("pair release sweep failed: %s", error, exc_info=True)
        return {"purged": 0, "unavailable": _code(error)}


def _left_for_a_person(database: Any, work: list[Work]) -> list[dict]:
    out = []
    for item in work:
        if item.action != "review":
            continue
        try:
            reasons = review_reasons(database, item.purge_request_id)
        except Exception as error:
            logger.warning("review reasons unreadable purge=%s: %s",
                           item.purge_request_id, error, exc_info=True)
            reasons = []
        out.append({**item.view(), "reasons": reasons})
    return out


def run_due_deletions(database: Any, *, execute: bool,
                      limit: int = DEFAULT_LIMIT,
                      now: Optional[datetime] = None,
                      release_storage: Any = None) -> dict:
    """One completion run. Returns the report for the cron's log.
    ``release_storage`` is the release bucket's storage (default: R2)."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    work = collect(database, now)
    actionable = [item for item in work if item.action != "review"]
    outcomes: list[dict] = []
    report: dict[str, Any] = {
        "job_version": JOB_VERSION,
        "mode": "execute" if execute else "dry_run",
        "due": len(actionable),
        "deferred": max(0, len(actionable) - limit),
        "outcomes": outcomes,
        "left_for_a_person": [],
    }
    if not execute:
        outcomes.extend(_handle(database, item, execute=False)
                        for item in actionable[:limit])
        report["left_for_a_person"] = _left_for_a_person(database, work)
        return report
    client = database.client
    holder = f"deletion-completion:{uuid.uuid4()}"
    lease = {"p_holder": holder, "p_seconds": LEASE_SECONDS}
    if not _lease(client, "claim_deletion_completion_lease_v1", lease):
        report["skipped"] = "LEASE_HELD"
        return report
    try:
        for item in actionable[:limit]:
            if not _lease(client, "claim_deletion_completion_lease_v1", lease):
                # Our lease ran out and another run holds it: stop here.
                report["stopped"] = "LEASE_LOST"
                break
            outcomes.append(_handle(database, item, execute=True))
        if "stopped" not in report:
            report["release_sweep"] = _sweep_releases(database, release_storage)
    finally:
        _lease(client, "release_deletion_completion_lease_v1", {"p_holder": holder})
    # Read again: a request this run stopped is now one a person must see.
    report["left_for_a_person"] = _left_for_a_person(database, collect(database, now))
    return report


def review_queue(database: Any, now: Optional[datetime] = None) -> dict:
    """The operator's read: what is due and what waits for a person."""
    work = collect(database, now)
    return {
        "due": [item.view() for item in work if item.action != "review"],
        "left_for_a_person": _left_for_a_person(database, work),
    }
