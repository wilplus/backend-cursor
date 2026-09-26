"""Archive a project (founder 2026-09-26, decisions log N14).

The ⋯ on each project row offers Archive: the project leaves the project list
and nothing else changes. Its takes, words, Ideal Text and feedback stay as
they are, and the owner can bring it back. Deleting is a separate request
(services/project_deletion.py).

Owner-scoped: a project is archived or restored only by its owner, and an
erased (tombstoned) project cannot be either.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class ProjectArchiveError(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


class ProjectArchiveService:
    def __init__(self, database: Any) -> None:
        self.client = getattr(database, "client", None)

    def _set(self, principal_id: str, project_id: str, value: str | None) -> dict:
        if self.client is None:
            raise ProjectArchiveError("PROJECT_ARCHIVE_UNAVAILABLE", 503)
        rows = (
            self.client.table("projects")
            .update({"archived_at": value})
            .eq("id", str(project_id))
            .eq("owner_principal_id", str(principal_id))
            .is_("tombstoned_at", "null")
            .execute().data or []
        )
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            raise ProjectArchiveError("PROJECT_NOT_FOUND", 404)
        return {"project_id": str(row.get("id")),
                "archived_at": row.get("archived_at")}

    def archive(self, principal_id: str, project_id: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return self._set(principal_id, project_id, now)

    def restore(self, principal_id: str, project_id: str) -> dict:
        return self._set(principal_id, project_id, None)
