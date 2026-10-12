"""Reads and writes for the AI voice's two tables (migration 0462).

Kept out of ``services/db.py`` on purpose (the 2026-10-12 refactors move
logic out of the god-files): this module is the only place that knows the
table shapes. Every call takes the app's database object and uses its
PostgREST client; a failed read returns the empty answer and logs only ids.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

_log = logging.getLogger(__name__)

CLONES = "ai_voice_clones"
CYCLES = "ai_voice_cycles"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result: Any) -> list[dict]:
    return list(getattr(result, "data", None) or [])


def _first(result: Any) -> Optional[dict]:
    rows = _rows(result)
    return rows[0] if rows else None


def get_clone(database: Any, owner_user_id: str) -> Optional[dict]:
    try:
        res = (database.client.table(CLONES).select("*")
               .eq("owner_user_id", str(owner_user_id)).limit(1).execute())
        return _first(res)
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: clone read failed owner=%s: %s",
                     owner_user_id, type(error).__name__, exc_info=True)
        return None


def save_clone(database: Any, owner_user_id: str, fields: dict) -> Optional[dict]:
    row = {"owner_user_id": str(owner_user_id), **fields, "updated_at": _now()}
    try:
        res = database.client.table(CLONES).upsert(
            row, on_conflict="owner_user_id").execute()
        return (_rows(res) or [row])[0]
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: clone write failed owner=%s: %s",
                     owner_user_id, type(error).__name__, exc_info=True)
        return None


def claim_clone_creation(database: Any, owner_user_id: str) -> bool:
    """Move the clone to 'creating' only from 'none' or 'failed', so two
    workers never both create one (the update matches no row for the second)."""
    try:
        existing = get_clone(database, owner_user_id)
        if existing is None:
            res = database.client.table(CLONES).insert({
                "owner_user_id": str(owner_user_id), "status": "creating",
                "attempts": 1}).execute()
            return bool(_rows(res))
        if existing.get("status") not in ("none", "failed") or not existing.get("enabled", True):
            return False
        res = (database.client.table(CLONES)
               .update({"status": "creating",
                        "attempts": int(existing.get("attempts") or 0) + 1,
                        "updated_at": _now()})
               .eq("owner_user_id", str(owner_user_id))
               .eq("status", str(existing.get("status")))
               .execute())
        return bool(_rows(res))
    except Exception as error:  # noqa: BLE001 — a lost race is a no
        _log.info("ai voice: clone claim refused owner=%s: %s",
                  owner_user_id, type(error).__name__, exc_info=True)
        return False


def get_cycle(database: Any, practice_id: str) -> Optional[dict]:
    try:
        res = (database.client.table(CYCLES).select("*")
               .eq("practice_id", str(practice_id)).limit(1).execute())
        return _first(res)
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: cycle read failed practice=%s: %s",
                     practice_id, type(error).__name__, exc_info=True)
        return None


def create_cycle(database: Any, row: dict) -> tuple[Optional[dict], bool]:
    """(row, created). A second request for the same practice gets the first
    request's row back (UNIQUE practice_id), never a second clip."""
    try:
        res = database.client.table(CYCLES).insert(row).execute()
        rows = _rows(res)
        if rows:
            return rows[0], True
    except Exception as error:  # noqa: BLE001 — the unique key said "exists"
        _log.info("ai voice: cycle insert lost to an existing row practice=%s: %s",
                  row.get("practice_id"), type(error).__name__)
    return get_cycle(database, str(row.get("practice_id"))), False


def update_cycle(database: Any, cycle_id: str, fields: dict) -> None:
    try:
        (database.client.table(CYCLES).update({**fields, "updated_at": _now()})
         .eq("id", str(cycle_id)).execute())
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: cycle write failed id=%s: %s",
                     cycle_id, type(error).__name__, exc_info=True)


def claim_cycle(database: Any, cycle_id: str) -> bool:
    """pending → analyzing, for exactly one worker."""
    try:
        res = (database.client.table(CYCLES)
               .update({"status": "analyzing", "updated_at": _now()})
               .eq("id", str(cycle_id)).eq("status", "pending").execute())
        return bool(_rows(res))
    except Exception as error:  # noqa: BLE001
        _log.info("ai voice: cycle claim refused id=%s: %s",
                  cycle_id, type(error).__name__, exc_info=True)
        return False


def owner_cycles(database: Any, owner_user_id: str, limit: int = 50) -> list[dict]:
    try:
        res = (database.client.table(CYCLES).select("*")
               .eq("owner_user_id", str(owner_user_id))
               .order("created_at", desc=True).limit(limit).execute())
        return _rows(res)
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: cycles read failed owner=%s: %s",
                     owner_user_id, type(error).__name__, exc_info=True)
        return []


def cycles_since(database: Any, since: datetime, *,
                 owner_user_id: Optional[str] = None) -> list[dict]:
    """Cycles that called the provider since ``since`` (for the limits)."""
    try:
        query = (database.client.table(CYCLES)
                 .select("id,owner_user_id,characters,credits_estimated,generation_attempts")
                 .gte("created_at", since.isoformat())
                 .gt("generation_attempts", 0))
        if owner_user_id:
            query = query.eq("owner_user_id", str(owner_user_id))
        return _rows(query.execute())
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: usage read failed: %s", type(error).__name__, exc_info=True)
        raise


def clones_created_since(database: Any, since: datetime) -> int:
    try:
        res = (database.client.table(CLONES).select("owner_user_id")
               .gte("created_at", since.isoformat()).execute())
        return len(_rows(res))
    except Exception as error:  # noqa: BLE001
        _log.warning("ai voice: clone count failed: %s", type(error).__name__, exc_info=True)
        raise


def start_of_day() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_month() -> datetime:
    return start_of_day().replace(day=1)


def thirty_days_ago() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=30)
