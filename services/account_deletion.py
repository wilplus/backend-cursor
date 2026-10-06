"""Account deletion with a seven-day cancel window (founder 2026-10-05,
decisions log N48.4: Q14 A, Q19 A; migration 0422).

A request is recorded at once and blocks processing at once: the status
function counts it as a block, and the request cancels in-flight jobs,
permits and carryovers, takes the person's pairs out of the releasable
pool (PLF-T2, PLF-T3) and voids every pair release that holds one (0454).
Nothing of the person's is deleted for seven days, and until then the
requester may cancel, which lifts the block. When the window has passed the
completion run (services/deletion_completion.py) starts the purge.

Storage is ``account_deletion_requests`` (0422), apart from
``data_purge_requests`` as 0364 keeps project requests apart: the purge
request is created only when the window has passed.

What the speaker's app reads is ``deletion_view``: ids, state, dates and
whether it can still be cancelled. Never a reason, a count or an owner id.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

COLUMNS = (
    "id,acquisition_principal_id,state,requested_at,completes_after,"
    "cancelled_at,started_at,completed_at,purge_request_id"
)
#: A request that still governs the person: blocked, and shown as ended.
LIVE_STATES = ("pending", "started", "done")
_REASON = re.compile(r"^[A-Z0-9_]{1,64}$")
_MISSING = ("42P01", "42883", "PGRST202", "PGRST205")

# Database refusal -> (public code, HTTP status).
_REFUSALS = {
    "ACCOUNT_DELETION_NOT_FOUND": ("ACCOUNT_DELETION_NOT_FOUND", 404),
    "ACCOUNT_DELETION_WINDOW_CLOSED": ("ACCOUNT_DELETION_WINDOW_CLOSED", 409),
    "ACCOUNT_DELETION_ALREADY_STARTED": (
        "ACCOUNT_DELETION_ALREADY_STARTED", 409),
    "ACCOUNT_DELETION_IDEMPOTENCY_KEY_REQUIRED": (
        "IDEMPOTENCY_KEY_REQUIRED", 422),
    "PROCESSING_PRINCIPAL_UNRESOLVED": ("PROCESSING_PRINCIPAL_UNRESOLVED", 403),
}


class AccountDeletionRefused(Exception):
    """A refusal with its public code and status; the route maps it."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _one(data: Any) -> Optional[dict]:
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) and data.get("id") else None


def _is_missing(error: BaseException) -> bool:
    text = f"{getattr(error, 'code', '') or ''} {error}"
    return any(code in text for code in _MISSING)


def _at(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def reason_code(raw: Any) -> str:
    """A machine reason, or the default: free text never reaches evidence."""
    text = str(raw or "").strip().upper()
    return text if _REASON.match(text) else "ACCOUNT_DELETION"


def cancellable(row: dict, now: Optional[datetime] = None) -> bool:
    """Pending, and the window has not closed. The database decides on the
    cancel itself; this only tells the app whether to offer it."""
    ends = _at(row.get("completes_after"))
    moment = now or datetime.now(timezone.utc)
    return row.get("state") == "pending" and ends is not None and moment < ends


def deletion_view(row: Optional[dict], now: Optional[datetime] = None) -> Optional[dict]:
    """What the speaker's app reads about their account deletion.

    ``purge_id`` and ``request_id`` are the same id: the one the cancel and
    the status read take. ``trigger_kind`` and ``id`` keep the shape the
    deletion status read had before 0422."""
    if not row:
        return None
    request_id = str(row.get("id"))
    return {
        "purge_id": request_id,
        "request_id": request_id,
        "id": request_id,
        "kind": "account",
        "trigger_kind": "account_deletion",
        "project_id": None,
        "state": row.get("state"),
        "requested_at": row.get("requested_at"),
        "completes_after": row.get("completes_after"),
        "cancellable": cancellable(row, now),
        "cancelled_at": row.get("cancelled_at"),
        "completed_at": row.get("completed_at"),
    }


def learning_stopped(database: Any, principal_id: Optional[str]) -> bool:
    """Whether this person's service is ending (0422), so nothing of theirs
    may be copied for training or join a release.

    A database double without a client, or a database the migration has not
    reached, answers no, as before 0422. Any other failure answers yes: a
    copy that waits a week costs nothing; one made after a deletion request
    breaks a promise."""
    client = getattr(database, "client", None)
    if client is None or not principal_id:
        return False
    try:
        value = client.rpc("phase1_learning_stopped_v1", {
            "p_acquisition_principal_id": str(principal_id),
        }).execute().data
    except Exception as error:
        if _is_missing(error):
            return False
        logger.warning("learning-stop read failed principal=%s: %s",
                       principal_id, error, exc_info=True)
        return True
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = next(iter(value.values()), None)
    return value is True


class AccountDeletionService:
    def __init__(self, database: Any) -> None:
        self.client = database.client

    def _rpc(self, name: str, params: dict) -> dict:
        try:
            result = self.client.rpc(name, params).execute()
        except Exception as error:
            text = str(error)
            for raised, (code, status) in _REFUSALS.items():
                if raised in text:
                    raise AccountDeletionRefused(code, status) from error
            if _is_missing(error):
                raise AccountDeletionRefused(
                    "ACCOUNT_DELETION_UNAVAILABLE", 503) from error
            raise
        row = _one(result.data)
        if not row:
            raise RuntimeError(f"{name} returned no row")
        return row

    def request(self, principal_id: str, *, idempotency_key: str,
                reason: Any = None) -> dict:
        return self._rpc("request_phase1_account_deletion_v1", {
            "p_acquisition_principal_id": str(principal_id),
            "p_idempotency_key": str(idempotency_key or ""),
            "p_reason_code": reason_code(reason),
        })

    def cancel(self, principal_id: str, request_id: str) -> dict:
        if not is_uuid(request_id):
            raise AccountDeletionRefused("ACCOUNT_DELETION_NOT_FOUND", 404)
        return self._rpc("cancel_phase1_account_deletion_v1", {
            "p_acquisition_principal_id": str(principal_id),
            "p_request_id": str(request_id),
        })

    def find(self, principal_id: str, request_id: str) -> Optional[dict]:
        """The person's own request by id, or None (unknown, someone
        else's, or the table not migrated)."""
        if not is_uuid(request_id):
            return None
        return self._select(principal_id, ("id", str(request_id)))

    def live_for_principal(self, principal_id: str) -> Optional[dict]:
        """The request that governs the person now (pending, started or
        done), newest first; None when there is none."""
        return self._select(principal_id, None)

    def _select(self, principal_id: str,
                by: Optional[tuple[str, str]]) -> Optional[dict]:
        query = (self.client.table("account_deletion_requests")
                 .select(COLUMNS)
                 .eq("acquisition_principal_id", str(principal_id)))
        query = (query.eq(by[0], by[1]) if by
                 else query.in_("state", list(LIVE_STATES)))
        try:
            rows = query.limit(50).execute().data or []
        except Exception as error:
            if _is_missing(error):
                return None
            raise
        rows = [row for row in rows if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("requested_at") or ""), reverse=True)
        return _one(rows)
