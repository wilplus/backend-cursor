"""Rename an owned, unerased project without changing its contents."""
from __future__ import annotations

from typing import Any


class ProjectRenameError(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


class ProjectRenameService:
    def __init__(self, database: Any) -> None:
        self.client = getattr(database, "client", None)

    def rename(
        self, principal_id: str, project_id: str, display_name: str,
    ) -> dict:
        if self.client is None:
            raise ProjectRenameError("PROJECT_RENAME_UNAVAILABLE", 503)
        rows = (
            self.client.table("projects")
            .update({"display_name": str(display_name)})
            .eq("id", str(project_id))
            .eq("owner_principal_id", str(principal_id))
            .is_("tombstoned_at", "null")
            .execute().data or []
        )
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row:
            raise ProjectRenameError("PROJECT_NOT_FOUND", 404)
        return {
            "project_id": str(row.get("id")),
            "display_name": str(row.get("display_name") or ""),
        }
