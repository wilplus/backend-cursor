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

from postgrest.types import ReturnMethod

from services.data_purge_registry import (
    DEPENDENCIES, DETACH_LINKS, LINEAGE_TOMBSTONES,
    PurgeDependency,
    before_its_rule,
    carve_outs,
    classified_relations,
    dependency_by_code,
    dependency_manifest_sha256,
    row_matches,
)
from services.lab_audio_storage import (
    delete_verified_lab_audio_object,
    verify_lab_audio_object_absent,
)
from services.provider_deletion import resolve_provider_operation

RESOLVER_VERSION = "phase1-purge-resolver-v4"
#: The target kinds `freeze_phase1_purge_inventory_v4` accepts; it files any
#: other kind as `unknown`, which stops the whole erasure (0362).
FREEZE_TARGET_KINDS = frozenset({
    "database_row", "r2_object", "supabase_object", "transcript",
    "derived_feedback", "processing_queue", "provider_operation",
    "coach_packet", "cache", "dataset_lineage", "model_lineage",
})
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
    speaker_ids: tuple[str, ...] = ()
    practice_ids: tuple[str, ...] = ()
    practice_attempt_ids: tuple[str, ...] = ()
    exercise_audio_lineage_ids: tuple[str, ...] = ()
    exercise_blind_packet_ids: tuple[str, ...] = ()
    delivery_job_ids: tuple[str, ...] = ()
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
            "speaker": self.speaker_ids,
            "practice": self.practice_ids,
            "practice_attempt": self.practice_attempt_ids,
            "exercise_audio_lineage": self.exercise_audio_lineage_ids,
            "exercise_blind_packet": self.exercise_blind_packet_ids,
            "delivery_job": self.delivery_job_ids,
        }.get(locator_kind, ())

    def payload(self) -> dict[str, list[str]]:
        return {
            key: list(getattr(self, key))
            for key in (
                "principal_ids", "user_ids", "project_ids", "take_ids",
                "recording_ids", "snippet_ids", "permit_ids", "job_ids",
                "speaker_ids", "practice_ids", "practice_attempt_ids",
                "exercise_audio_lineage_ids", "exercise_blind_packet_ids",
                "delivery_job_ids",
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
        # Read once per inventory: each rule's active rows, each schedule.
        self._rulings: dict[str, list[dict]] = {}
        self._schedules: dict[str, bool] = {}

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
        # The whole graph comes from SQL (0362). The freeze recomputes it and
        # requires an identical one, so a key added here and not there made
        # every account deletion fail PURGE_SUBJECT_GRAPH_MISMATCH.
        result = self.client.rpc("resolve_phase1_purge_subject_graph_v3", {
            "p_acquisition_principal_id": principal_id,
        }).execute()
        payload = _one(result.data)
        if not payload:
            raise RuntimeError("PURGE_SUBJECT_GRAPH_RESOLUTION_FAILED")
        if any(not isinstance(payload.get(key), list) for key in GRAPH_KEYS):
            raise RuntimeError("PURGE_SUBJECT_GRAPH_INVALID")
        graph = SubjectGraph(**{
            key: tuple(str(item) for item in payload[key]) for key in GRAPH_KEYS
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

    def _ruling_rule(
        self, dependency: PurgeDependency,
        existing_relations: frozenset[str] | None,
    ) -> dict | None:
        """The ACTIVE signed row that decides a ruled dependency (retention
        schedule v1.4): its rule_code AND its evidence category, or None."""
        code = str(dependency.ruled_by or "")
        if not code:
            return None
        if code not in self._rulings:
            rows = self._rows(
                "data_retention_rules", "id,rule_code,evidence_category,active",
                selector="rule_code", values=(code,),
                existing_relations=existing_relations,
            )
            self._rulings[code] = [
                row for row in rows
                if row.get("active") is True and row.get("rule_code") == code
            ]
        return next((
            row for row in self._rulings[code]
            if row.get("evidence_category") == dependency.retention_category
        ), None)

    def _schedule_registered(
        self, version: str | None,
        existing_relations: frozenset[str] | None,
    ) -> bool:
        """Retention schedule `version` is registered: its row in
        processing_legal_artifacts, which only its signed script writes
        (scripts/phase1_retention_schedule_v1_5.sql). No version asked for:
        nothing to check. A read that fails answers no."""
        if not version:
            return True
        if version not in self._schedules:
            try:
                rows = self._rows(
                    "processing_legal_artifacts", "id,artifact_kind,version",
                    selector="version", values=(version,),
                    existing_relations=existing_relations,
                )
            except RuntimeError:
                rows = []
            self._schedules[version] = any(
                row.get("artifact_kind") == "retention_schedule"
                and row.get("version") == version for row in rows
            )
        return self._schedules[version]

    def _decided(
        self, dependency: PurgeDependency,
        existing_relations: frozenset[str] | None,
    ) -> tuple[PurgeDependency, dict | None]:
        """What a dependency does in THIS inventory, and the rule behind it.

        A ruled dependency acts on its disposition only while its rule is
        active, and a v1.5 one only while v1.5 is registered as well. Until
        then it is exactly the registry entry it was before (`before_its_rule`):
        an `external_review` row still stops the erasure, a job row is still
        deleted. Every other dependency is unchanged and has no ruling."""
        if not dependency.ruled_by:
            return dependency, None
        rule = self._ruling_rule(dependency, existing_relations)
        if rule is None or not self._schedule_registered(
                dependency.schedule, existing_relations):
            return before_its_rule(dependency), None
        return dependency, rule

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
        dependency, ruling = self._decided(dependency, existing_relations)
        if dependency.carved_from and ruling is None:
            # Not decided yet: its rows are still the original entry's, which
            # counts them and stops the erasure for review, as before.
            return None
        values = graph.values(dependency.locator_kind)
        count = self._count(dependency, values, existing_relations)
        metadata: dict[str, Any] = {
            "dependency_code": dependency.code,
            "relation": dependency.relation,
            "selector_column": dependency.selector_column,
            "locator_kind": dependency.locator_kind,
            "locator_values": list(values),
            "disposition": dependency.disposition,
            "delete_order": dependency.delete_order,
        }
        if dependency.schedule:
            metadata["retention_schedule"] = dependency.schedule
        if dependency.row_filter:
            metadata["row_filter"] = [list(c) for c in dependency.row_filter]
        if count and dependency.disposition == "external_review":
            return PurgeTarget(
                "unknown", f"dependency:{dependency.code}", count,
                {**metadata, "reason_code": "EXPLICIT_RESOLVER_REQUIRED"},
            )
        if count and dependency.disposition in ("retain", "tombstone"):
            category = str(dependency.retention_category or "")
            rule = ruling or self._retention_rule(category, existing_relations)
            if not rule:
                return PurgeTarget(
                    "unknown", f"dependency:{dependency.code}", count,
                    {**metadata, "reason_code": "RETENTION_RULE_UNRESOLVED"},
                )
            metadata["retention_rule_id"] = str(rule["id"])
        elif count and ruling is not None:
            # A ruled delete (a v1.4 product record) names the signed rule
            # it is deleted under; the append-only tables' trigger reads it
            # (0424) and the purge event records it.
            metadata["retention_rule_id"] = str(ruling["id"])
        kind = dependency.target_kind
        if kind not in FREEZE_TARGET_KINDS:
            # The rows ARE database rows; the registry's label says what they
            # point at. Kept, but not as a kind the freeze would call unknown.
            metadata["registry_target_kind"] = kind
            kind = "database_row"
        return PurgeTarget(
            kind, f"dependency:{dependency.code}", count, metadata,
        )

    def _count(
        self,
        dependency: PurgeDependency,
        values: Sequence[str],
        existing_relations: frozenset[str] | None = None,
    ) -> int:
        """One subject's rows in one registry relation.

        Read as before where service_role may read. Where it may not — 0327
        revoked it from the coaching-bundle tables — the read failed and filed
        the dependency as unknown, which stops the whole erasure; those are
        counted in SQL as the function's owner instead (0362). Any other
        failure still raises, and still fails closed.
        """
        if not values:
            return 0
        if dependency.row_filter or carve_outs(dependency.code):
            return self._split_count(dependency, values, existing_relations)
        try:
            return len(self._rows(
                dependency.relation, dependency.selector_column,
                selector=dependency.selector_column, values=values,
                existing_relations=existing_relations,
            ))
        except RuntimeError as error:
            if not str(error).startswith("UNRESOLVED_DEPENDENCY:"):
                raise
        result = self.client.rpc("count_phase1_purge_dependency_rows_v1", {
            "p_relation": dependency.relation,
            "p_selector_column": dependency.selector_column,
            "p_values": list(values),
        }).execute()
        count = result.data
        if isinstance(count, list):
            count = count[0] if count else None
        if isinstance(count, dict):
            count = next(iter(count.values()), None)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise RuntimeError(f"PURGE_COUNT_INVALID:{dependency.relation}")
        return count

    def _split_count(
        self,
        dependency: PurgeDependency,
        values: Sequence[str],
        existing_relations: frozenset[str] | None,
    ) -> int:
        """The rows of a split table (v1.5, N50 P2 and P4) this entry holds:
        the ones its row_filter keeps, less, for the table's original entry,
        every row a decided carve-out claims. Read as rows by the row's own
        columns, never counted in SQL; a read that fails raises, and the
        inventory files the entry as unknown."""
        claimed = [
            carve for carve in carve_outs(dependency.code)
            if self._decided(carve, existing_relations)[1] is not None
        ]
        columns = {dependency.selector_column}
        for entry in (dependency, *claimed):
            columns.update(column for column, _op, _value in entry.row_filter)
        rows = self._rows(
            dependency.relation, ",".join(sorted(columns)),
            selector=dependency.selector_column, values=values,
            existing_relations=existing_relations,
        )
        return sum(
            1 for row in rows
            if row_matches(dependency, row)
            and not any(row_matches(carve, row) for carve in claimed)
        )

    def _practice_targets(
        self,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        """Practice recordings (0334).

        Its own method because _storage_targets is grandfathered by the
        complexity ratchet and may only come down — but also because this is a
        third registry with its own reason to exist: processing_audio_objects
        requires a recording_attempt_id and a practice attempt is not a Take.

        Without this, a purged speaker's practice ROWS were deleted and their
        recordings stayed in the bucket with nothing pointing at them.
        """
        targets: list[PurgeTarget] = []
        rows = self._rows(
            "processing_practice_objects",
            "id,storage_provider,bucket,object_key,exact_bytes_sha256,deleted_at",
            selector="acquisition_principal_id", values=graph.principal_ids,
            existing_relations=existing_relations,
        )
        for row in rows:
            provider = str(row.get("storage_provider") or "")
            already_purged = row.get("deleted_at") is not None
            targets.append(PurgeTarget(
                "r2_object" if provider == "r2" else "supabase_object",
                f"practice-object:{row.get('id')}",
                0 if already_purged else 1, {
                    "provider": provider,
                    "bucket": str(row.get("bucket") or ""),
                    "key": str(row.get("object_key") or ""),
                    "sha256": str(row.get("exact_bytes_sha256") or ""),
                    "source_relation": "processing_practice_objects",
                    "source_id": str(row.get("id") or ""),
                    "already_purged": already_purged,
                }))
        return targets

    def _corpus_targets(
        self,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        """Training copies' audio (0375, P4). Account erasure deletes every
        copy (C3), so each object is a storage target like a practice one;
        the rows follow as the `training_corpus_items` dependency."""
        targets: list[PurgeTarget] = []
        rows = self._rows(
            "training_corpus_items",
            "id,storage_provider,bucket,storage_key,object_sha256,state",
            selector="acquisition_principal_id", values=graph.principal_ids,
            existing_relations=existing_relations,
        )
        for row in rows:
            if not row.get("storage_key"):
                continue
            provider = str(row.get("storage_provider") or "")
            already_purged = row.get("state") == "purged"
            targets.append(PurgeTarget(
                "r2_object" if provider == "r2" else "supabase_object",
                f"training-copy:{row.get('id')}",
                0 if already_purged else 1, {
                    "provider": provider,
                    "bucket": str(row.get("bucket") or ""),
                    "key": str(row.get("storage_key") or ""),
                    "sha256": str(row.get("object_sha256") or ""),
                    "source_relation": "training_corpus_items",
                    "source_id": str(row.get("id") or ""),
                    "already_purged": already_purged,
                }))
        return targets

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
        targets.extend(self._practice_targets(graph, existing_relations))
        targets.extend(self._corpus_targets(graph, existing_relations))

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

    def _reference_video_targets(
        self,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        """A reference video made for the speaker that is not library content
        goes with the account (v1.5, N50 P4). Its file has no recorded hash or
        provider, so the purge cannot prove it deleted the right bytes: each
        one stops the erasure for review first, as an upload does. Nothing
        here before v1.5 decides the entry."""
        own = dependency_by_code("reference_videos_own")
        if own is None or own.relation not in existing_relations:
            return []
        if self._decided(own, existing_relations)[1] is None:
            return []
        try:
            rows = self._rows(
                own.relation, "id,is_universal",
                selector=own.selector_column,
                values=graph.values(own.locator_kind),
                existing_relations=existing_relations,
            )
        except Exception as error:  # noqa: BLE001 - fail-closed inventory
            return [PurgeTarget(
                "unknown", "reference-video:inventory", 1,
                {"reason_code": "REFERENCE_VIDEO_INVENTORY_FAILED",
                 "error_code": _error_code(error)},
            )]
        return [
            PurgeTarget(
                "unknown", f"reference-video:{row.get('id')}", 1,
                {"reason_code": "REFERENCE_VIDEO_PROVIDER_AND_SHA256_UNRESOLVED",
                 "source_relation": own.relation,
                 "source_id": str(row.get("id") or "")},
            )
            for row in rows if row_matches(own, row)
        ]

    def _checked_v1_5_deletes(
        self, targets: list[PurgeTarget],
    ) -> list[PurgeTarget]:
        """Retention schedule v1.5's deletes, checked before anything is
        frozen (0429, check_phase1_purge_delete_v1). A delete whose rows the
        service may not delete, or that a row this purge does not delete
        first still points at (a kept decision, a kept job, a lineage row
        no graph reaches), would fail part-way, after the audio is gone: it
        stops the whole erasure for review instead."""
        deletes = sorted(
            (target for target in targets
             if target.target_ref.startswith("dependency:")
             and target.target_kind != "unknown"
             and target.metadata.get("disposition") == "delete"
             and target.initial_match_count > 0),
            key=lambda target: _execution_key(
                target.metadata.get("delete_order"), target.target_kind,
                target.target_ref),
        )
        if not any(t.metadata.get("retention_schedule") for t in deletes):
            return targets
        # A filtered entry deletes only some of the rows its selector
        # reaches, so it never counts as covering another table's rows.
        plan = [
            {"relation": target.metadata.get("relation"),
             "selector_column": target.metadata.get("selector_column"),
             "locator_values": list(target.metadata.get("locator_values") or []),
             "rank": rank}
            for rank, target in enumerate(deletes)
            if not target.metadata.get("row_filter")
        ]
        checked = {
            target.target_ref: self._checked_delete(target, plan, rank)
            for rank, target in enumerate(deletes)
            if target.metadata.get("retention_schedule")
        }
        return [checked.get(target.target_ref, target) for target in targets]

    def _checked_delete(
        self, target: PurgeTarget, plan: list[dict], rank: int,
    ) -> PurgeTarget:
        metadata = dict(target.metadata)
        try:
            result = self.client.rpc("check_phase1_purge_delete_v1", {
                "p_relation": str(metadata.get("relation") or ""),
                "p_selector_column": str(metadata.get("selector_column") or ""),
                "p_values": [str(value) for value in
                             metadata.get("locator_values") or []],
                "p_rank": rank,
                "p_plan": plan,
            }).execute()
            verdict = _one(result.data) or {}
        except Exception as error:  # noqa: BLE001 - fail-closed inventory
            return PurgeTarget(
                "unknown", target.target_ref, target.initial_match_count,
                {**metadata, "reason_code": "DELETE_CHECK_UNAVAILABLE",
                 "error_code": _error_code(error)},
            )
        blocked = verdict.get("blocked_by") or {}
        if verdict.get("can_delete") is not True:
            reason = "PURGE_CANNOT_DELETE_HERE"
        elif blocked:
            reason = "KEPT_ROWS_STILL_POINT_HERE"
        else:
            return target
        return PurgeTarget(
            "unknown", target.target_ref, target.initial_match_count,
            {**metadata, "reason_code": reason, "blocked_by": blocked},
        )

    def build_inventory(self, purge_request_id: str) -> dict[str, Any]:
        self._rulings = {}
        self._schedules = {}
        request = self._request(purge_request_id)
        # A project request is never run account-wide, nor an account
        # request project-wide (0380; the manifest guard refuses it too).
        if (request.get("trigger_kind") == "project_deletion") != (
                self.scope == "project"):
            raise RuntimeError("PURGE_SCOPE_MISMATCH")
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
        targets = self._checked_v1_5_deletes(targets)
        targets.extend(self._storage_targets(graph, existing))
        targets.extend(self._reference_video_targets(graph, existing))
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
        result = self.client.rpc(self.freeze_function, {
            "p_purge_request_id": purge_request_id,
            "p_resolver_version": self.resolver_version,
            "p_dependency_manifest_sha256": self._dependency_manifest_sha(),
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
        if str(manifest.get("resolver_version") or "") != self.resolver_version:
            raise RuntimeError("PURGE_RESOLVER_VERSION_CHANGED")
        if (
            str(manifest.get("dependency_manifest_sha256") or "")
            != self._dependency_manifest_sha()
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
            "id,purge_request_id,target_kind,target_ref,state,"
            "initial_match_count,remaining_match_count,metadata",
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
        dependency = self._dependency(str(metadata.get("dependency_code") or ""))
        if dependency is None:
            self._resolve(target, state="unknown", remaining=1,
                          error_code="DEPENDENCY_CONTRACT_MISSING")
            return
        if dependency.ruled_by:
            # A ruled dependency resolves as the inventory decided it: its
            # rule active (its disposition) or not (before_its_rule). Never
            # anything else.
            frozen = str(metadata.get("disposition") or "")
            if frozen != dependency.disposition:
                dependency = before_its_rule(dependency)
            if frozen != dependency.disposition:
                self._resolve(target, state="failed", remaining=1,
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
        if dependency.disposition == "tombstone":
            self._resolve_tombstone(target, dependency, initial)
            return
        if dependency.disposition != "delete":
            self._resolve(target, state="unknown", remaining=initial,
                          error_code="EXPLICIT_RESOLVER_REQUIRED")
            return
        delete_rule_id = str(metadata.get("retention_rule_id") or "") or None
        if dependency.ruled_by and not self._rule_still_active(delete_rule_id):
            # The signed rule was withdrawn after the freeze: delete nothing.
            self._resolve(target, state="failed", remaining=initial,
                          error_code="RETENTION_RULE_INACTIVE")
            return
        try:
            # Nothing asked back: the service may hold DELETE and SELECT on
            # the selecting columns alone (0429); the rows left are counted.
            _filtered(
                self.client.table(dependency.relation).delete(
                    returning=ReturnMethod.minimal),
                dependency, values,
            ).execute()
            remaining = self._count(dependency, values)
            state = "deleted" if remaining == 0 else "failed"
            self._resolve(
                target, state=state, remaining=remaining,
                error_code=None if remaining == 0 else "ROWS_REMAIN_AFTER_DELETE",
                retention_rule_id=delete_rule_id,
            )
        except Exception as error:  # noqa: BLE001 - database boundary
            self._resolve(target, state="failed", remaining=initial,
                          error_code=_error_code(error))

    def _rule_still_active(self, rule_id: str | None) -> bool:
        """The rule a ruled delete was frozen under is still active now. A
        read that fails answers no: the delete waits rather than guesses."""
        if not rule_id:
            return False
        try:
            rows = self._rows(
                "data_retention_rules", "id,active", selector="id",
                values=(rule_id,),
            )
        except RuntimeError:
            return False
        return any(row.get("active") is True for row in rows)

    def _resolve_tombstone(
        self, target: Mapping[str, Any], dependency: PurgeDependency,
        initial: int,
    ) -> None:
        """Wipe the user content of rows retained evidence still points at,
        then keep the bare rows under the deletion-evidence rule (N9).

        Two kinds: the project row (0368) and a take's permanent record, its
        take session included (0379, founder N12). Each database function
        scrubs exactly the rows inside this request's frozen graph and reports
        how many are still not blank; anything but zero is a failure. Both
        are idempotent, so every target of the kind may call its own. A third
        keeps library content and clears only its link to the speaker
        (DETACH_LINKS, v1.5 P4), under the same not-blank check."""
        metadata = target.get("metadata") or {}
        rule_id = str(metadata.get("retention_rule_id") or "")
        try:
            if dependency.relation in DETACH_LINKS:
                outcome = self._detach(target, dependency)
            else:
                if dependency.relation == "projects":
                    function = "tombstone_phase1_purge_projects_v1"
                elif dependency.relation in LINEAGE_TOMBSTONES:
                    function = "tombstone_phase1_purge_lineage_v1"
                else:
                    raise RuntimeError("TOMBSTONE_RELATION_UNSUPPORTED")
                result = self.client.rpc(function, {
                    "p_purge_request_id": str(
                        target.get("purge_request_id") or ""),
                }).execute()
                outcome = _one(result.data) or {}
            if int(outcome.get("not_blank") or 0) != 0:
                raise RuntimeError("TOMBSTONE_CONTENT_REMAINS")
            self._resolve(target, state="retained", remaining=initial,
                          retention_rule_id=rule_id,
                          evidence_extra={"tombstoned": outcome.get("tombstoned")})
        except Exception as error:  # noqa: BLE001 - database boundary
            self._resolve(target, state="failed", remaining=initial,
                          error_code=_error_code(error))

    def _detach(
        self, target: Mapping[str, Any], dependency: PurgeDependency,
    ) -> dict:
        """Library content (v1.5, N50 P4): clear only the columns that link
        each frozen row to the speaker; the row and its video stay. Reports,
        as the tombstone functions do, how many rows still name the
        speaker."""
        metadata = target.get("metadata") or {}
        values = [str(value) for value in metadata.get("locator_values") or []]
        if values:
            _filtered(
                self.client.table(dependency.relation).update(
                    {column: None for column in DETACH_LINKS[dependency.relation]},
                    returning=ReturnMethod.minimal),
                dependency, values,
            ).execute()
        return {"tombstoned": int(target.get("initial_match_count") or 0),
                "not_blank": self._count(dependency, values)}

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
        graph = self._graph_from_manifest(manifest.get("subject_graph") or {})
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
            key=lambda row: _execution_key(
                (row.get("metadata") or {}).get("delete_order"),
                row.get("target_kind"), row.get("target_ref")),
        ):
            self._resolve_dependency(target, graph)

    def finalize(self, purge_request_id: str) -> dict:
        targets = self._targets(purge_request_id)
        evidence = _sha({
            "purge_request_id": purge_request_id,
            "resolver_version": self.resolver_version,
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

    # The account scope. `ProjectPurgeOrchestrator`
    # (services/data_purge_project_scope.py) narrows it to one project.
    scope = "account"
    resolver_version = RESOLVER_VERSION
    freeze_function = "freeze_phase1_purge_inventory_v4"

    def _dependency(self, code: str) -> PurgeDependency | None:
        return dependency_by_code(code)

    def _graph_from_manifest(self, raw_graph: Mapping[str, Any]) -> SubjectGraph:
        return SubjectGraph(**{
            key: tuple(str(item) for item in raw_graph.get(key, []))
            for key in GRAPH_KEYS
        })

    def _dependency_manifest_sha(self) -> str:
        return dependency_manifest_sha256()


#: The keys of the account subject graph, in the order the freeze stores them.
GRAPH_KEYS: tuple[str, ...] = (
    "principal_ids", "user_ids", "project_ids", "take_ids",
    "recording_ids", "snippet_ids", "permit_ids", "job_ids",
    "speaker_ids", "practice_ids", "practice_attempt_ids",
    "exercise_audio_lineage_ids", "exercise_blind_packet_ids",
    "delivery_job_ids",
    "unresolved_legacy_take_ids",
)


def _execution_key(delete_order: Any, target_kind: Any, target_ref: Any,
                   ) -> tuple[int, str, str]:
    """The order resolve_targets runs dependency targets in: by delete order,
    ties by kind then reference, the order the freeze inserted them."""
    return (int(delete_order or 0), str(target_kind or ""),
            str(target_ref or ""))


def _filtered(query: Any, dependency: PurgeDependency,
              values: Sequence[str]) -> Any:
    """A PostgREST query narrowed to exactly the rows this entry selects:
    its selector over the frozen values, and every row_filter condition."""
    query = (
        query.eq(dependency.selector_column, values[0]) if len(values) == 1
        else query.in_(dependency.selector_column, list(values))
    )
    for column, operator, value in dependency.row_filter:
        if operator == "eq":
            query = query.eq(column, value)
        elif operator == "is_null":
            query = query.is_(column, "null")
        elif operator == "in":
            query = query.in_(column, value.split(","))
        else:
            raise ValueError(f"ROW_FILTER_OPERATOR_UNKNOWN:{operator}")
    return query
