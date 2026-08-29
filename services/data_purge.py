"""Durable, fail-closed Phase-1 data-purge orchestration.

The resolver inventories only explicit, reviewed ownership paths. Unknown or
mixed-purpose dependencies become ``review_required`` targets; they are never
silently treated as deleted. Routes may request a purge, but only this
orchestrator resolves targets and asks the database to finalize the request.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from services.lab_audio_storage import delete_verified_lab_audio_object


RESOLVER_VERSION = "phase1-purge-resolver-v1"


def _one(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return None


def _hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PurgeTarget:
    target_kind: str
    target_ref: str

    def payload(self) -> dict[str, str]:
        return {"target_kind": self.target_kind, "target_ref": self.target_ref}


class DataPurgeOrchestrator:
    """Inventory, verify, and resolve a single attributable purge request."""

    _CANONICAL_TABLES = (
        ("processing_audio_objects", "database_row"),
        ("processing_recording_attempts", "database_row"),
        ("phase1_processing_jobs", "processing_queue"),
        ("processing_provider_permits", "provider_operation"),
        ("processing_authorization_snapshots", "database_row"),
    )
    # These relations mix content with current product state or historical
    # evidence. They remain explicit review targets until a separate,
    # table-specific destructive resolver has been accepted.
    _MIXED_PURPOSE_DEPENDENCIES = (
        "projects", "v2_sessions", "recordings", "snippets",
        "coach_review_delivery_outbox", "coach_snippet_drafts",
        "ideal_text_blocks", "ideal_text_revisions", "lounge_messages",
    )

    def __init__(self, database: Any) -> None:
        self.database = database
        self.client = database.client

    def _request(self, purge_request_id: str) -> dict:
        row = _one(
            self.client.table("data_purge_requests")
            .select("id,acquisition_principal_id,trigger_kind,state")
            .eq("id", purge_request_id).limit(1).execute().data
        )
        if not row:
            raise ValueError("PURGE_REQUEST_NOT_FOUND")
        return row

    def _rows(
        self, table: str, principal_id: str, columns: str = "id",
    ) -> list[dict]:
        try:
            result = (
                self.client.table(table).select(columns)
                .eq("acquisition_principal_id", principal_id).execute()
            )
            return [r for r in (result.data or []) if isinstance(r, dict)]
        except Exception as error:
            raise RuntimeError(f"UNRESOLVED_DEPENDENCY:{table}") from error

    def build_inventory(self, purge_request_id: str) -> list[PurgeTarget]:
        request = self._request(purge_request_id)
        principal_id = str(request["acquisition_principal_id"])
        targets: list[PurgeTarget] = []
        for table, kind in self._CANONICAL_TABLES:
            columns = (
                "id,storage_provider,bucket,object_key,exact_bytes_sha256"
                if table == "processing_audio_objects" else "id"
            )
            for row in self._rows(table, principal_id, columns):
                targets.append(PurgeTarget(kind, f"{table}:{row['id']}"))
                if table == "processing_audio_objects":
                    coordinates = json.dumps({
                        "provider": row.get("storage_provider"),
                        "bucket": row.get("bucket"),
                        "key": row.get("object_key"),
                        "sha256": row.get("exact_bytes_sha256"),
                    }, sort_keys=True, separators=(",", ":"))
                    targets.append(PurgeTarget(
                        "r2_object" if row.get("storage_provider") == "r2"
                        else "supabase_object",
                        coordinates,
                    ))
        for dependency in self._MIXED_PURPOSE_DEPENDENCIES:
            targets.append(PurgeTarget(
                "unknown", f"mixed-purpose:{dependency}:principal:{principal_id}"
            ))
        return targets

    def freeze_inventory(self, purge_request_id: str) -> dict:
        targets = [item.payload() for item in self.build_inventory(purge_request_id)]
        result = self.client.rpc("freeze_phase1_purge_inventory_v1", {
            "p_purge_request_id": purge_request_id,
            "p_resolver_version": RESOLVER_VERSION,
            "p_targets": targets,
        }).execute()
        return _one(result.data) or {}

    def _object_is_shared(
        self, *, provider: str, bucket: str, key: str, owner_id: str,
    ) -> bool:
        result = (
            self.client.table("processing_audio_objects").select("id")
            .eq("storage_provider", provider).eq("bucket", bucket)
            .eq("object_key", key).neq("acquisition_principal_id", owner_id)
            .limit(1).execute()
        )
        return bool(result.data)

    def resolve_storage_targets(self, purge_request_id: str) -> None:
        request = self._request(purge_request_id)
        owner_id = str(request["acquisition_principal_id"])
        rows = (
            self.client.table("data_purge_targets")
            .select("id,target_kind,target_ref,state")
            .eq("purge_request_id", purge_request_id)
            .in_("target_kind", ["r2_object", "supabase_object"])
            .eq("state", "pending").execute().data or []
        )
        for target in rows:
            target_id = str(target["id"])
            coordinates: dict[str, Any] = {}
            try:
                raw = json.loads(str(target["target_ref"]))
                if not isinstance(raw, dict):
                    raise ValueError("invalid object target")
                coordinates = raw
                provider = str(raw.get("provider") or "")
                bucket = str(raw.get("bucket") or "")
                key = str(raw.get("key") or "")
                expected_hash = str(raw.get("sha256") or "")
                if self._object_is_shared(
                    provider=provider, bucket=bucket, key=key, owner_id=owner_id,
                ):
                    raise RuntimeError("SHARED_OBJECT_REVIEW_REQUIRED")
                deleted = delete_verified_lab_audio_object(
                    key, bucket=bucket, storage_provider=provider,
                    expected_sha256=expected_hash,
                )
                if not deleted:
                    raise RuntimeError("OBJECT_DELETION_NOT_VERIFIED")
                state, error_code = "deleted", None
            except Exception as error:
                state, error_code = "failed", type(error).__name__
            evidence = _hash({
                "purge_request_id": purge_request_id,
                "target_id": target_id,
                "state": state,
                "expected_object_sha256": coordinates.get("sha256"),
                "error_code": error_code,
            })
            self.client.rpc("resolve_phase1_purge_target_v1", {
                "p_target_id": target_id,
                "p_state": state,
                "p_evidence_sha256": evidence,
                "p_last_error_code": error_code,
                "p_retention_rule_id": None,
            }).execute()

    def finalize(self, purge_request_id: str) -> dict:
        targets = (
            self.client.table("data_purge_targets").select("id,state")
            .eq("purge_request_id", purge_request_id).execute().data or []
        )
        evidence = _hash({
            "purge_request_id": purge_request_id,
            "resolver_version": RESOLVER_VERSION,
            "targets": sorted(
                ({"id": str(t.get("id")), "state": str(t.get("state"))}
                 for t in targets), key=lambda item: item["id"],
            ),
        })
        result = self.client.rpc("finalize_phase1_purge_v1", {
            "p_purge_request_id": purge_request_id,
            "p_evidence_sha256": evidence,
        }).execute()
        return _one(result.data) or {}

    def run(self, purge_request_id: str) -> dict:
        frozen = self.freeze_inventory(purge_request_id)
        self.resolve_storage_targets(purge_request_id)
        final = self.finalize(purge_request_id)
        return {"inventory": frozen, "result": final}
