"""Durable, fail-closed Phase-1 data-purge orchestration.

The worker freezes an attributable subject graph and a complete target
manifest before deleting anything. Unknown relations, legacy storage without
exact byte lineage, missing retention rules, missing provider contracts, and
shared objects stop the run before the first destructive call.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from services.data_purge_registry import (
    DEPENDENCIES,
    PurgeDependency,
    classified_relations,
    dependency_by_code,
    dependency_manifest_sha256,
)
from services.lab_audio_storage import (
    delete_verified_lab_audio_object,
    verify_lab_audio_object_absent,
)
from services.provider_deletion import resolve_provider_operation

RESOLVER_VERSION = "phase1-purge-resolver-v3"
_MISSING_RELATION_CODES = {"42P01", "PGRST205"}


def _one(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return None


def _sha(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _error_code(error: BaseException) -> str:
    code = str(getattr(error, "code", "") or "")
    return code or type(error).__name__


def _missing_relation(error: BaseException) -> bool:
    return _error_code(error) in _MISSING_RELATION_CODES


@dataclass(frozen=True)
class SubjectGraph:
    principal_ids: tuple[str, ...]
    user_ids: tuple[str, ...] = ()
    project_ids: tuple[str, ...] = ()
    take_ids: tuple[str, ...] = ()
    recording_ids: tuple[str, ...] = ()
    snippet_ids: tuple[str, ...] = ()
    permit_ids: tuple[str, ...] = ()
    job_ids: tuple[str, ...] = ()
    unresolved_legacy_take_ids: tuple[str, ...] = ()

    def values(self, locator_kind: str) -> tuple[str, ...]:
        return {
            "principal": self.principal_ids,
            "user": self.user_ids,
            "project": self.project_ids,
            "take": self.take_ids,
            "recording": self.recording_ids,
            "snippet": self.snippet_ids,
            "permit": self.permit_ids,
            "job": self.job_ids,
        }.get(locator_kind, ())

    def payload(self) -> dict[str, list[str]]:
        return {
            key: list(getattr(self, key))
            for key in (
                "principal_ids", "user_ids", "project_ids", "take_ids",
                "recording_ids", "snippet_ids", "permit_ids", "job_ids",
                "unresolved_legacy_take_ids",
            )
        }


@dataclass(frozen=True)
class PurgeTarget:
    target_kind: str
    target_ref: str
    initial_match_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        return {
            "target_kind": self.target_kind,
            "target_ref": self.target_ref,
            "initial_match_count": self.initial_match_count,
            "metadata": dict(self.metadata),
        }


class DataPurgeOrchestrator:
    """Inventory, preflight, resolve, and verify one purge request."""

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
        self,
        relation: str,
        columns: str,
        *,
        selector: str | None = None,
        values: Sequence[str] = (),
        existing_relations: frozenset[str] | None = None,
    ) -> list[dict]:
        if existing_relations is not None and relation not in existing_relations:
            return []
        # A missing subject coordinate means "no rows", never "remove the
        # filter". Treating an empty IN-list as an unfiltered query would leak
        # another subject's rows into the frozen graph.
        if selector is not None and not values:
            return []
        output: list[dict] = []
        offset = 0
        page_size = 500
        while True:
            query = self.client.table(relation).select(columns)
            if selector and values:
                query = (
                    query.eq(selector, values[0]) if len(values) == 1
                    else query.in_(selector, list(values))
                )
            try:
                result = query.range(offset, offset + page_size - 1).execute()
            except Exception as error:
                if _missing_relation(error):
                    return []
                raise RuntimeError(
                    f"UNRESOLVED_DEPENDENCY:{relation}:{_error_code(error)}"
                ) from error
            page = [row for row in (result.data or []) if isinstance(row, dict)]
            output.extend(page)
            if len(page) < page_size:
                return output
            offset += page_size

    def _catalog(self) -> dict:
        result = self.client.rpc("audit_phase1_purge_catalog_v1", {
            "p_allowlisted_relations": sorted(classified_relations()),
        }).execute()
        row = _one(result.data)
        if not row or not str(row.get("catalog_sha256") or ""):
            raise RuntimeError("PURGE_CATALOG_AUDIT_FAILED")
        return row

    @staticmethod
    def _ids(rows: Iterable[Mapping[str, Any]], key: str) -> set[str]:
        return {
            str(row[key]) for row in rows
            if row.get(key) not in (None, "")
        }

    def build_subject_graph(
        self, principal_id: str, _existing_relations: frozenset[str],
    ) -> SubjectGraph:
        result = self.client.rpc("resolve_phase1_purge_subject_graph_v1", {
            "p_acquisition_principal_id": principal_id,
        }).execute()
        payload = _one(result.data)
        if not payload:
            raise RuntimeError("PURGE_SUBJECT_GRAPH_RESOLUTION_FAILED")
        keys = (
            "principal_ids", "user_ids", "project_ids", "take_ids",
            "recording_ids", "snippet_ids", "permit_ids", "job_ids",
            "unresolved_legacy_take_ids",
        )
        if any(not isinstance(payload.get(key), list) for key in keys):
            raise RuntimeError("PURGE_SUBJECT_GRAPH_INVALID")
        graph = SubjectGraph(**{
            key: tuple(str(item) for item in payload[key]) for key in keys
        })
        if principal_id not in graph.principal_ids:
            raise RuntimeError("PURGE_SUBJECT_GRAPH_PRINCIPAL_MISMATCH")
        return graph

    def _retention_rule(
        self, category: str, existing_relations: frozenset[str],
    ) -> dict | None:
        rows = self._rows(
            "data_retention_rules", "id,rule_code,evidence_category,active",
            selector="evidence_category", values=(category,),
            existing_relations=existing_relations,
        )
        return next((row for row in rows if row.get("active") is True), None)

    def _active_provider_contract(
        self, provider: str, operation_kind: str,
        existing_relations: frozenset[str],
    ) -> dict | None:
        contracts = self._rows(
            "processing_provider_deletion_contracts", "*", selector="provider",
            values=(provider,), existing_relations=existing_relations,
        )
        contracts = [
            row for row in contracts
            if str(row.get("operation_kind") or "") == operation_kind
        ]
        if not contracts:
            return None
        ids = tuple(sorted(self._ids(contracts, "id")))
        events = self._rows(
            "processing_provider_deletion_contract_events",
            "contract_id,event_kind,occurred_at,event_sequence",
            selector="contract_id",
            values=ids, existing_relations=existing_relations,
        )
        latest: dict[str, dict] = {}
        for event in sorted(
            events, key=lambda row: int(row.get("event_sequence") or 0),
        ):
            latest[str(event.get("contract_id") or "")] = event
        active = [
            row for row in contracts
            if (latest.get(str(row.get("id"))) or {}).get("event_kind")
            == "activated"
        ]
        if len(active) != 1:
            return None
        return active[0]

    def _dependency_target(
        self,
        dependency: PurgeDependency,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> PurgeTarget | None:
        if dependency.relation not in existing_relations:
            return None
        values = graph.values(dependency.locator_kind)
        if not values:
            count = 0
        else:
            rows = self._rows(
                dependency.relation, dependency.selector_column,
                selector=dependency.selector_column, values=values,
                existing_relations=existing_relations,
            )
            count = len(rows)
        metadata: dict[str, Any] = {
            "dependency_code": dependency.code,
            "relation": dependency.relation,
            "selector_column": dependency.selector_column,
            "locator_kind": dependency.locator_kind,
            "locator_values": list(values),
            "disposition": dependency.disposition,
            "delete_order": dependency.delete_order,
        }
        if count and dependency.disposition == "external_review":
            return PurgeTarget(
                "unknown", f"dependency:{dependency.code}", count,
                {**metadata, "reason_code": "EXPLICIT_RESOLVER_REQUIRED"},
            )
        if count and dependency.disposition == "retain":
            category = str(dependency.retention_category or "")
            rule = self._retention_rule(category, existing_relations)
            if not rule:
                return PurgeTarget(
                    "unknown", f"dependency:{dependency.code}", count,
                    {**metadata, "reason_code": "RETENTION_RULE_UNRESOLVED"},
                )
            metadata["retention_rule_id"] = str(rule["id"])
        return PurgeTarget(
            dependency.target_kind, f"dependency:{dependency.code}", count,
            metadata,
        )

    def _storage_targets(
        self,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        targets: list[PurgeTarget] = []
        canonical_recordings: set[str] = set()
        objects = self._rows(
            "processing_audio_objects",
            "id,recording_attempt_id,storage_provider,bucket,object_key,"
            "exact_bytes_sha256,deleted_at",
            selector="acquisition_principal_id", values=graph.principal_ids,
            existing_relations=existing_relations,
        )
        deletion_events = self._rows(
            "processing_audio_object_deletion_events", "audio_object_id",
            selector="acquisition_principal_id", values=graph.principal_ids,
            existing_relations=existing_relations,
        )
        deleted_audio_ids = self._ids(deletion_events, "audio_object_id")
        attempt_rows = self._rows(
            "processing_recording_attempts", "id,recording_id",
            selector="acquisition_principal_id", values=graph.principal_ids,
            existing_relations=existing_relations,
        )
        attempt_recording = {
            str(row.get("id")): str(row.get("recording_id"))
            for row in attempt_rows if row.get("id") and row.get("recording_id")
        }
        canonical_coordinates: set[tuple[str, str, str]] = set()
        for row in objects:
            canonical_recordings.add(
                attempt_recording.get(str(row.get("recording_attempt_id")), "")
            )
            provider = str(row.get("storage_provider") or "")
            bucket = str(row.get("bucket") or "")
            key = str(row.get("object_key") or "")
            canonical_coordinates.add((provider, bucket, key))
            kind = "r2_object" if provider == "r2" else "supabase_object"
            already_purged = (
                row.get("deleted_at") is not None
                or str(row.get("id") or "") in deleted_audio_ids
            )
            targets.append(PurgeTarget(
                kind, f"audio-object:{row.get('id')}",
                0 if already_purged else 1, {
                "provider": provider, "bucket": bucket, "key": key,
                "sha256": str(row.get("exact_bytes_sha256") or ""),
                "source_relation": "processing_audio_objects",
                "source_id": str(row.get("id") or ""),
                "already_purged": already_purged,
            }))
        orphans = self._rows(
            "processing_orphan_objects",
            "id,storage_provider,bucket,object_key,exact_bytes_sha256,status",
            selector="acquisition_principal_id", values=graph.principal_ids,
            existing_relations=existing_relations,
        )
        for row in orphans:
            provider = str(row.get("storage_provider") or "")
            bucket = str(row.get("bucket") or "")
            key = str(row.get("object_key") or "")
            status = str(row.get("status") or "")
            if status == "referenced":
                if (provider, bucket, key) not in canonical_coordinates:
                    targets.append(PurgeTarget(
                        "unknown", f"orphan-object:{row.get('id')}", 1,
                        {"reason_code": "REFERENCED_ORPHAN_LINEAGE_MISSING"},
                    ))
                continue
            kind = "r2_object" if provider == "r2" else "supabase_object"
            already_purged = status == "deleted"
            targets.append(PurgeTarget(
                kind, f"orphan-object:{row.get('id')}",
                0 if already_purged else 1, {
                "provider": provider, "bucket": bucket, "key": key,
                "sha256": str(row.get("exact_bytes_sha256") or ""),
                "source_relation": "processing_orphan_objects",
                "source_id": str(row.get("id") or ""),
                "already_purged": already_purged,
            }))
        legacy = set(graph.recording_ids) - {value for value in canonical_recordings if value}
        for recording_id in sorted(legacy):
            targets.append(PurgeTarget(
                "unknown", f"legacy-audio:{recording_id}", 1,
                {"reason_code": "EXACT_AUDIO_OBJECT_LINEAGE_MISSING"},
            ))
        uploads = self._rows(
            "user_uploaded_files", "id,r2_bucket,r2_key", selector="user_id",
            values=graph.user_ids, existing_relations=existing_relations,
        )
        for row in uploads:
            targets.append(PurgeTarget(
                "unknown", f"user-upload:{row.get('id')}", 1,
                {"reason_code": "UPLOAD_PROVIDER_AND_SHA256_UNRESOLVED"},
            ))
        return targets

    def _provider_targets(
        self,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        permits = self._rows(
            "processing_provider_permits", "id,provider,operation_kind",
            selector="id", values=graph.permit_ids,
            existing_relations=existing_relations,
        )
        permit_map = {str(row.get("id")): row for row in permits}
        operations = self._rows(
            "processing_provider_operations",
            "id,permit_id,provider_operation_ref,event_kind",
            selector="permit_id", values=graph.permit_ids,
            existing_relations=existing_relations,
        )
        targets: list[PurgeTarget] = []
        for operation in operations:
            permit = permit_map.get(str(operation.get("permit_id") or ""), {})
            provider = str(permit.get("provider") or "")
            kind = str(permit.get("operation_kind") or "")
            contract = self._active_provider_contract(
                provider, kind, existing_relations,
            )
            if contract is None:
                targets.append(PurgeTarget(
                    "unknown", f"provider-operation:{operation.get('id')}", 1,
                    {"reason_code": "PROVIDER_DELETION_CONTRACT_UNRESOLVED",
                     "provider": provider, "operation_kind": kind},
                ))
                continue
            targets.append(PurgeTarget(
                "provider_operation", f"provider-operation:{operation.get('id')}",
                1, {
                    "provider": provider, "operation_kind": kind,
                    "provider_operation_id": str(operation.get("id") or ""),
                    "provider_operation_ref": operation.get("provider_operation_ref"),
                    "contract_id": str(contract.get("id") or ""),
                    "resolution_mode": contract.get("resolution_mode"),
                    "provider_object_prefix": contract.get("provider_object_prefix"),
                    "retention_rule_id": contract.get("retention_rule_id"),
                },
            ))
        return targets

    def build_inventory(self, purge_request_id: str) -> dict[str, Any]:
        request = self._request(purge_request_id)
        catalog = self._catalog()
        existing = frozenset(
            str(item) for item in catalog.get("existing_allowlisted_relations", [])
        )
        graph = self.build_subject_graph(
            str(request["acquisition_principal_id"]), existing,
        )
        targets: list[PurgeTarget] = []
        if graph.unresolved_legacy_take_ids:
            targets.append(PurgeTarget(
                "unknown", "legacy-take-ownership:unresolved",
                len(graph.unresolved_legacy_take_ids), {
                    "reason_code": "LEGACY_TAKE_OWNER_PRINCIPAL_UNRESOLVED",
                    "take_ids": list(graph.unresolved_legacy_take_ids),
                },
            ))
        for dependency in DEPENDENCIES:
            try:
                target = self._dependency_target(dependency, graph, existing)
                if target:
                    targets.append(target)
            except Exception as error:  # noqa: BLE001 - fail-closed inventory
                targets.append(PurgeTarget(
                    "unknown", f"dependency:{dependency.code}", 0,
                    {"reason_code": "DEPENDENCY_INVENTORY_FAILED",
                     "error_code": _error_code(error)},
                ))
        targets.extend(self._storage_targets(graph, existing))
        targets.extend(self._provider_targets(graph, existing))
        targets.sort(key=lambda item: (item.target_kind, item.target_ref))
        return {
            "request": request, "catalog": catalog, "graph": graph,
            "targets": targets,
        }

    def freeze_inventory(self, purge_request_id: str) -> dict:
        existing = _one(
            self.client.table("data_purge_inventory_manifests").select("*")
            .eq("purge_request_id", purge_request_id).limit(1).execute().data
        )
        if existing:
            self._assert_frozen_contract(existing, purge_request_id)
            return {"purge_request_id": purge_request_id, "state": "frozen",
                    "inventory_sha256": existing.get("target_manifest_sha256")}
        inventory = self.build_inventory(purge_request_id)
        graph_payload = inventory["graph"].payload()
        target_payload = [item.payload() for item in inventory["targets"]]
        result = self.client.rpc("freeze_phase1_purge_inventory_v3", {
            "p_purge_request_id": purge_request_id,
            "p_resolver_version": RESOLVER_VERSION,
            "p_dependency_manifest_sha256": dependency_manifest_sha256(),
            "p_subject_graph": graph_payload,
            "p_targets": target_payload,
            "p_catalog_sha256": inventory["catalog"]["catalog_sha256"],
            "p_catalog_unknown_relations": inventory["catalog"].get(
                "unknown_relations", []
            ),
        }).execute()
        return _one(result.data) or {}

    def _manifest(self, purge_request_id: str) -> dict:
        manifest = _one(
            self.client.table("data_purge_inventory_manifests").select("*")
            .eq("purge_request_id", purge_request_id).limit(1).execute().data
        )
        if not manifest:
            raise RuntimeError("PURGE_INVENTORY_NOT_FROZEN")
        return manifest

    def _assert_frozen_contract(
        self, manifest: Mapping[str, Any], purge_request_id: str,
    ) -> None:
        """Refuse deletion if code or catalog changed after inventory freeze."""
        if str(manifest.get("resolver_version") or "") != RESOLVER_VERSION:
            raise RuntimeError("PURGE_RESOLVER_VERSION_CHANGED")
        if (
            str(manifest.get("dependency_manifest_sha256") or "")
            != dependency_manifest_sha256()
        ):
            raise RuntimeError("PURGE_DEPENDENCY_MANIFEST_CHANGED")
        current_catalog = self._catalog()
        if current_catalog.get("unknown_relations"):
            raise RuntimeError("UNCLASSIFIED_SUBJECT_RELATION")
        if (
            str(current_catalog.get("catalog_sha256") or "")
            != str(manifest.get("catalog_sha256") or "")
        ):
            raise RuntimeError("PURGE_CATALOG_CHANGED_AFTER_FREEZE")
        request = self._request(purge_request_id)
        current_graph = self.build_subject_graph(
            str(request["acquisition_principal_id"]),
            frozenset(str(item) for item in current_catalog.get(
                "existing_allowlisted_relations", []
            )),
        ).payload()
        if current_graph != (manifest.get("subject_graph") or {}):
            raise RuntimeError("PURGE_SUBJECT_GRAPH_CHANGED_AFTER_FREEZE")

    def _targets(self, purge_request_id: str) -> list[dict]:
        return self._rows(
            "data_purge_targets",
            "id,target_kind,target_ref,state,initial_match_count,"
            "remaining_match_count,metadata",
            selector="purge_request_id", values=(purge_request_id,),
        )

    def _resolve(
        self,
        target: Mapping[str, Any],
        *,
        state: str,
        remaining: int,
        error_code: str | None = None,
        retention_rule_id: str | None = None,
        evidence_extra: Mapping[str, Any] | None = None,
    ) -> None:
        evidence = _sha({
            "target_id": str(target.get("id") or ""), "state": state,
            "remaining_match_count": remaining, "error_code": error_code,
            "retention_rule_id": retention_rule_id,
            **dict(evidence_extra or {}),
        })
        self.client.rpc("resolve_phase1_purge_target_v3", {
            "p_target_id": str(target["id"]), "p_state": state,
            "p_evidence_sha256": evidence,
            "p_remaining_match_count": remaining,
            "p_last_error_code": error_code,
            "p_retention_rule_id": retention_rule_id,
        }).execute()

    def _object_is_shared(
        self, provider: str, bucket: str, key: str, principal_ids: Sequence[str],
    ) -> bool:
        for relation in ("processing_audio_objects", "processing_orphan_objects"):
            try:
                rows = (
                    self.client.table(relation).select("acquisition_principal_id")
                    .eq("storage_provider", provider).eq("bucket", bucket)
                    .eq("object_key", key).execute().data or []
                )
            except Exception as error:
                if _missing_relation(error):
                    continue
                raise
            if any(
                str(row.get("acquisition_principal_id") or "")
                not in set(principal_ids) for row in rows if isinstance(row, dict)
            ):
                return True
        return False

    def _resolve_object(
        self, purge_request_id: str, target: Mapping[str, Any], graph: SubjectGraph,
    ) -> None:
        metadata = target.get("metadata") or {}
        provider, bucket, key = (
            str(metadata.get(name) or "") for name in ("provider", "bucket", "key")
        )
        expected_hash = str(metadata.get("sha256") or "")
        try:
            if (
                int(target.get("initial_match_count") or 0) == 0
                and metadata.get("already_purged") is True
                and verify_lab_audio_object_absent(
                    key, bucket=bucket, storage_provider=provider,
                )
            ):
                self._resolve(
                    target, state="not_found", remaining=0,
                    evidence_extra={"previously_verified_purge": True},
                )
                return
            if self._object_is_shared(
                provider, bucket, key, graph.principal_ids,
            ):
                raise RuntimeError("SHARED_OBJECT_REVIEW_REQUIRED")
            deleted = delete_verified_lab_audio_object(
                key, bucket=bucket, storage_provider=provider,
                expected_sha256=expected_hash,
            )
            if not deleted:
                raise RuntimeError("OBJECT_DELETION_NOT_VERIFIED")
            self.client.rpc("mark_phase1_storage_object_purged_v1", {
                "p_purge_request_id": purge_request_id,
                "p_source_relation": metadata.get("source_relation"),
                "p_source_id": metadata.get("source_id"),
                "p_storage_provider": provider, "p_bucket": bucket,
                "p_object_key": key,
                "p_exact_bytes_sha256": expected_hash,
            }).execute()
            self._resolve(target, state="deleted", remaining=0,
                          evidence_extra={"expected_sha256": expected_hash})
        except Exception as error:  # noqa: BLE001 - provider boundary
            self._resolve(
                target, state="failed", remaining=1,
                error_code=_error_code(error),
                evidence_extra={"expected_sha256": expected_hash},
            )

    def _resolve_dependency(
        self, target: Mapping[str, Any], graph: SubjectGraph,
    ) -> None:
        metadata = target.get("metadata") or {}
        dependency = dependency_by_code(str(metadata.get("dependency_code") or ""))
        if dependency is None:
            self._resolve(target, state="unknown", remaining=1,
                          error_code="DEPENDENCY_CONTRACT_MISSING")
            return
        values = graph.values(dependency.locator_kind)
        initial = int(target.get("initial_match_count") or 0)
        if initial == 0:
            self._resolve(target, state="not_found", remaining=0)
            return
        if dependency.disposition == "retain":
            rule_id = str(metadata.get("retention_rule_id") or "")
            self._resolve(target, state="retained", remaining=initial,
                          retention_rule_id=rule_id)
            return
        if dependency.disposition != "delete":
            self._resolve(target, state="unknown", remaining=initial,
                          error_code="EXPLICIT_RESOLVER_REQUIRED")
            return
        try:
            query = self.client.table(dependency.relation).delete()
            query = (
                query.eq(dependency.selector_column, values[0])
                if len(values) == 1 else
                query.in_(dependency.selector_column, list(values))
            )
            query.execute()
            remaining = len(self._rows(
                dependency.relation, dependency.selector_column,
                selector=dependency.selector_column, values=values,
            ))
            state = "deleted" if remaining == 0 else "failed"
            self._resolve(
                target, state=state, remaining=remaining,
                error_code=None if remaining == 0 else "ROWS_REMAIN_AFTER_DELETE",
            )
        except Exception as error:  # noqa: BLE001 - database boundary
            self._resolve(target, state="failed", remaining=initial,
                          error_code=_error_code(error))

    def _resolve_provider(self, target: Mapping[str, Any]) -> None:
        metadata = target.get("metadata") or {}
        result = resolve_provider_operation(
            contract={
                "provider": metadata.get("provider"),
                "resolution_mode": metadata.get("resolution_mode"),
                "provider_object_prefix": metadata.get("provider_object_prefix"),
                "retention_rule_id": metadata.get("retention_rule_id"),
            },
            provider=str(metadata.get("provider") or ""),
            provider_operation_ref=metadata.get("provider_operation_ref"),
        )
        self._resolve(
            target, state=result.state, remaining=result.remaining_match_count,
            error_code=result.error_code,
            retention_rule_id=result.retention_rule_id,
            evidence_extra={"contract_id": metadata.get("contract_id")},
        )

    def resolve_targets(self, purge_request_id: str) -> None:
        self._request(purge_request_id)
        targets = self._targets(purge_request_id)
        # Preflight is all-or-nothing. Unknown inventory means zero deletion.
        if any(str(row.get("state")) == "unknown" for row in targets):
            return
        manifest = self._manifest(purge_request_id)
        self._assert_frozen_contract(manifest, purge_request_id)
        raw_graph = manifest.get("subject_graph") or {}
        graph = SubjectGraph(**{
            key: tuple(str(item) for item in raw_graph.get(key, []))
            for key in (
                "principal_ids", "user_ids", "project_ids", "take_ids",
                "recording_ids", "snippet_ids", "permit_ids", "job_ids",
                "unresolved_legacy_take_ids",
            )
        })
        storage = [
            row for row in targets
            if row.get("state") == "pending"
            and row.get("target_kind") in ("r2_object", "supabase_object")
        ]
        dependencies = [
            row for row in targets
            if row.get("state") == "pending"
            and str(row.get("target_ref") or "").startswith("dependency:")
        ]
        providers = [
            row for row in targets
            if row.get("state") == "pending"
            and row.get("target_kind") == "provider_operation"
        ]
        for target in storage:
            self._resolve_object(purge_request_id, target, graph)
        for target in providers:
            self._resolve_provider(target)
        for target in sorted(
            dependencies,
            key=lambda row: int((row.get("metadata") or {}).get("delete_order") or 0),
        ):
            self._resolve_dependency(target, graph)

    def finalize(self, purge_request_id: str) -> dict:
        targets = self._targets(purge_request_id)
        evidence = _sha({
            "purge_request_id": purge_request_id,
            "resolver_version": RESOLVER_VERSION,
            "targets": sorted(({
                "id": str(row.get("id") or ""),
                "state": str(row.get("state") or ""),
                "remaining_match_count": row.get("remaining_match_count"),
            } for row in targets), key=lambda item: item["id"]),
        })
        result = self.client.rpc("finalize_phase1_purge_v3", {
            "p_purge_request_id": purge_request_id,
            "p_evidence_sha256": evidence,
        }).execute()
        return _one(result.data) or {}

    def run(self, purge_request_id: str) -> dict:
        frozen = self.freeze_inventory(purge_request_id)
        self.resolve_targets(purge_request_id)
        final = self.finalize(purge_request_id)
        return {"inventory": frozen, "result": final}
