"""Canonical Project/Take repository over the historical persistence schema.

Only this adapter knows that a Project is still mirrored to ``arc_id`` and a
Take is stored in ``v2_sessions``. Product services must use canonical names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from services.canonical_product import OwnerPrincipal, Project


class ProjectOwnershipError(LookupError):
    pass


@dataclass(frozen=True)
class ProjectOwner:
    principal: OwnerPrincipal
    guest_token: str | None = None


class ProjectRepository:
    def __init__(self, database):
        self.database = database

    def owner_for_user(self, user_id: str) -> OwnerPrincipal:
        row = self.database.get_owner_principal_for_user(str(user_id))
        if not row:
            row = self.database.create_user_owner_principal(str(user_id))
        if not row:
            raise ProjectOwnershipError("could not establish project owner")
        return OwnerPrincipal(str(row["id"]), str(user_id), False)

    def create_guest_owner(self, principal_id: str, secret_hash: str) -> OwnerPrincipal:
        row = self.database.create_guest_owner_principal(
            str(principal_id), str(secret_hash))
        if not row:
            raise ProjectOwnershipError("could not establish guest owner")
        return OwnerPrincipal(str(row["id"]), None, True)

    def get_principal(self, principal_id: str) -> dict | None:
        return self.database.get_owner_principal(str(principal_id))

    def create_project(
        self,
        *,
        project_id: str,
        owner_principal_id: str,
        display_name: str,
        setup: Mapping[str, Any],
        presentation_ref: str | None,
    ) -> Project:
        row = self.database.create_project({
            "id": str(project_id),
            "owner_principal_id": str(owner_principal_id),
            "display_name": display_name,
            "setup": dict(setup),
            "presentation_ref": presentation_ref,
        })
        if not row:
            raise ProjectOwnershipError("could not create project")
        return Project(
            id=str(row["id"]),
            owner_principal_id=str(row["owner_principal_id"]),
            display_name=str(row.get("display_name") or "Presentation"),
            setup=row.get("setup") if isinstance(row.get("setup"), dict) else {},
        )

    def require_owned_project(self, project_id: str, principal_id: str) -> dict:
        row = self.database.get_project_for_owner(
            str(project_id), str(principal_id))
        if not row:
            raise ProjectOwnershipError("project not found")
        return row

    def bind_take(
        self,
        take_id: str,
        project_id: str,
        principal_id: str,
    ) -> int | None:
        return self.database.bind_take_to_project(
            str(take_id), str(project_id), str(principal_id))

    def bind_variant(
        self,
        variant_id: str,
        project_id: str,
        principal_id: str,
        paired_take_id: str,
    ) -> int | None:
        return self.database.bind_recording_variant_to_project(
            str(variant_id),
            str(project_id),
            str(principal_id),
            str(paired_take_id),
        )

    def project_take_by_idempotency_key(
        self, project_id: str, idempotency_key: str,
    ) -> dict | None:
        return self.database.get_project_take_by_upload_key(
            str(project_id), str(idempotency_key))

    def project_takes(self, project_id: str) -> list[dict]:
        return self.database.get_arc_sessions(str(project_id)) or []

    def require_owned_take(
        self,
        project_id: str,
        take_id: str,
        principal_id: str,
    ) -> dict:
        row = self.database.get_project_take_for_owner(
            str(project_id), str(take_id), str(principal_id))
        if not row:
            raise ProjectOwnershipError("take not found")
        return row

    def claim_guest(self, principal_id: str, secret_hash: str, user_id: str) -> dict:
        row = self.database.claim_guest_owner_principal(
            str(principal_id), str(secret_hash), str(user_id))
        if not row:
            raise ProjectOwnershipError("guest owner claim rejected")
        return row
