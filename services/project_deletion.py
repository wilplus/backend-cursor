"""Project deletion requests (P1-A, founder 2026-09-25, decisions log N8).

The picker's ⋯ → Delete creates a REQUEST. An operator confirms it within 7
days; until then the project is locked and its owner may cancel. Nothing here
deletes anything: a confirmed request is executed by the governed Phase-1
purge once it can scope to one project (P1-B, spec §6).

Storage is ``project_deletion_requests`` (migration 0362), deliberately apart
from ``data_purge_requests`` so a project request can never be run as an
account-wide purge.

A missing table or function reads as "no request" so an unmigrated database
keeps today's behaviour; every other failure raises.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

OPEN_STATES = ("pending", "confirmed")
_COLUMNS = (
    "id,acquisition_principal_id,project_id,state,requested_at,due_at,"
    "cancelled_at,confirmed_at,completed_at"
)
_MISSING = ("42P01", "42883", "PGRST205", "PGRST202")

# RPC exception text → (public code, HTTP status). The function raises these
# names verbatim; anything else is a server fault.
_RPC_ERRORS = {
    "PROJECT_NOT_FOUND": ("PROJECT_NOT_FOUND", 404),
    "PROJECT_DELETION_NOT_PENDING": ("PROJECT_DELETION_NOT_PENDING", 409),
    "PROJECT_DELETION_ALREADY_CONFIRMED": (
        "PROJECT_DELETION_ALREADY_CONFIRMED", 409),
    "IDEMPOTENCY_CONFLICT": ("IDEMPOTENCY_CONFLICT", 409),
    "PROJECT_DELETION_IDEMPOTENCY_KEY_REQUIRED": ("INVALID_INPUT", 400),
}


class ProjectDeletionError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _code(error: BaseException) -> str:
    return str(getattr(error, "code", "") or "")


def _is_missing(error: BaseException) -> bool:
    code = _code(error)
    return code in _MISSING or any(c in str(error) for c in _MISSING)


def _one(data: Any) -> dict | None:
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) and data.get("id") else None


def public_view(row: dict | None) -> dict | None:
    """What a user or the picker sees: state and dates, never owner ids."""
    if not row:
        return None
    return {
        "request_id": str(row.get("id")),
        "project_id": str(row.get("project_id")),
        "state": row.get("state"),
        "requested_at": row.get("requested_at"),
        "due_at": row.get("due_at"),
        "cancelled_at": row.get("cancelled_at"),
    }


class ProjectDeletionService:
    def __init__(self, database: Any) -> None:
        # None only for a database double without a client; the real
        # database always has one. Reads then see no request.
        self.client = getattr(database, "client", None)

    def _rpc(self, name: str, params: dict) -> dict:
        try:
            result = self.client.rpc(name, params).execute()
        except Exception as error:
            text = str(error)
            for raised, (code, status) in _RPC_ERRORS.items():
                if raised in text:
                    raise ProjectDeletionError(code, raised, status) from error
            if _is_missing(error):
                raise ProjectDeletionError(
                    "PROJECT_DELETION_UNAVAILABLE",
                    "Project deletion is not available yet", 503,
                ) from error
            raise
        row = _one(result.data)
        if not row:
            raise RuntimeError(f"{name} returned no row")
        return row

    def request(
        self, principal_id: str, project_id: str, idempotency_key: str,
    ) -> dict:
        return self._rpc("request_project_deletion_v1", {
            "p_acquisition_principal_id": str(principal_id),
            "p_project_id": str(project_id),
            "p_idempotency_key": str(idempotency_key),
        })

    def cancel(self, principal_id: str, project_id: str) -> dict:
        return self._rpc("cancel_project_deletion_v1", {
            "p_acquisition_principal_id": str(principal_id),
            "p_project_id": str(project_id),
        })

    def open_for_projects(self, project_ids: Iterable[str]) -> dict[str, dict]:
        """{project_id: open request} for the given projects. Empty when the
        table is not migrated yet."""
        ids = sorted({str(p) for p in project_ids if p})
        if not ids or self.client is None:
            return {}
        try:
            rows = (
                self.client.table("project_deletion_requests")
                .select(_COLUMNS)
                .in_("project_id", ids)
                .in_("state", list(OPEN_STATES))
                .execute().data or []
            )
        except Exception as error:
            if _is_missing(error):
                return {}
            raise
        return {str(r["project_id"]): r for r in rows if r.get("project_id")}

    def open_for_project(self, project_id: str) -> dict | None:
        return self.open_for_projects([project_id]).get(str(project_id))

    def queue(self, states: Iterable[str] = OPEN_STATES, limit: int = 200) -> list[dict]:
        """Operator queue, oldest due first."""
        if self.client is None:
            return []
        try:
            return (
                self.client.table("project_deletion_requests")
                .select(_COLUMNS)
                .in_("state", list(states))
                .order("due_at")
                .limit(int(limit))
                .execute().data or []
            )
        except Exception as error:
            if _is_missing(error):
                return []
            raise


def with_deletion_state(database: Any, trainings: list[dict]) -> list[dict]:
    """Stamp each project in the picker feed with its open deletion request,
    or None (P1-A, N8): the picker shows "Deletion pending" and locks it.

    Best effort: a failed read leaves the list as it was and logs, rather
    than failing the whole picker over a lock marker.
    """
    try:
        open_requests = ProjectDeletionService(database).open_for_projects(
            t.get("arc_id") for t in trainings)
    except Exception as error:
        logger.warning("project deletion state unavailable: %s", error)
        open_requests = {}
    for training in trainings:
        training["deletion"] = public_view(
            open_requests.get(str(training.get("arc_id"))))
    return trainings
