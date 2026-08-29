from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

import pytest

from scripts import run_phase1_data_purge
from services import lab_audio_storage
from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_registry import (
    CASCADE_RELATIONS,
    DEPENDENCIES,
    DYNAMIC_RUNTIME_RELATIONS,
    NON_SUBJECT_RELATIONS,
    classified_relations,
)
from services.provider_deletion import resolve_provider_operation

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "migrations" / "add_phase1_deletion_completion.sql"
).read_text()


def _literal_runtime_relations() -> set[str]:
    names: set[str] = set()
    for root_name in ("routes", "services", "scripts"):
        for path in (ROOT / root_name).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "table":
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.add(first.value)
    return names


def _migration_subject_relations() -> set[str]:
    coordinate_columns = {
        "acquisition_principal_id", "owner_principal_id", "owner_user_id",
        "user_id", "claimed_user_id", "student_user_id", "project_id",
        "arc_id", "session_id", "recording_session_id", "take_session_id",
        "recording_id", "snippet_id", "source_owner_principal_id",
        "target_owner_principal_id", "processing_job_id", "permit_id",
    }
    names: set[str] = set()
    create_pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"(?:public\.)?([A-Za-z_][\w]*)\s*\((.*?)\);",
        re.IGNORECASE | re.DOTALL,
    )
    alter_pattern = re.compile(
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
        r"(?:public\.)?([A-Za-z_][\w]*)(.*?);",
        re.IGNORECASE | re.DOTALL,
    )
    for path in (ROOT / "migrations").glob("*.sql"):
        sql = re.sub(r"--.*", "", path.read_text(errors="ignore"))
        for match in create_pattern.finditer(sql):
            if any(
                re.search(rf"\b{re.escape(column)}\b", match.group(2), re.I)
                for column in coordinate_columns
            ):
                names.add(match.group(1).lower())
        for match in alter_pattern.finditer(sql):
            if any(
                re.search(
                    rf"\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
                    rf"{re.escape(column)}\b",
                    match.group(2), re.I,
                )
                for column in coordinate_columns
            ):
                names.add(match.group(1).lower())
    return names


def test_dependency_registry_classifies_runtime_relations_without_overlap():
    codes = [dependency.code for dependency in DEPENDENCIES]
    relations = {dependency.relation for dependency in DEPENDENCIES}
    assert len(codes) == len(set(codes))
    assert not relations.intersection(NON_SUBJECT_RELATIONS)
    assert not relations.intersection(CASCADE_RELATIONS)
    assert _literal_runtime_relations() <= classified_relations()
    assert DYNAMIC_RUNTIME_RELATIONS <= classified_relations()
    assert _migration_subject_relations() <= classified_relations()


def test_ambiguous_shared_and_mixed_purpose_paths_fail_closed():
    by_relation = {dependency.relation: dependency for dependency in DEPENDENCIES}
    assert by_relation["charisma_snippets"].disposition == "external_review"
    assert by_relation["life_notes"].disposition == "external_review"
    assert by_relation["ml_speaker_principals"].disposition == "external_review"
    assert by_relation["token_ledger"].disposition == "retain"
    assert by_relation["token_ledger"].retention_category == "financial_evidence"


def test_migration_seals_server_canonical_json_and_is_rpc_only():
    assert "computed_subject_graph_sha256" in MIGRATION
    assert "computed_target_manifest_sha256" in MIGRATION
    assert "digest(p_subject_graph::text" in MIGRATION
    assert "digest(p_targets::text" in MIGRATION
    assert "p_subject_graph_sha256" not in MIGRATION
    assert "p_target_manifest_sha256" not in MIGRATION
    assert "PURGE_MANIFEST_DUPLICATE_TARGET" in MIGRATION
    assert "register_phase1_provider_deletion_contract_v1" in MIGRATION
    assert "retire_phase1_provider_deletion_contract_v1" in MIGRATION
    assert "event_sequence BIGINT GENERATED ALWAYS AS IDENTITY" in MIGRATION
    assert (
        "GRANT SELECT ON public.data_purge_inventory_manifests TO service_role"
        in MIGRATION
    )
    assert "GRANT INSERT ON" not in MIGRATION
    assert "processing_audio_object_deletion_events" in MIGRATION
    assert "UPDATE public.processing_audio_objects SET deleted_at" not in MIGRATION
    assert "INSERT INTO public.processing_provider_deletion_contracts" in MIGRATION
    assert "VALUES ('openai'" not in MIGRATION.lower()


def test_provider_deletion_contract_modes_are_fail_closed():
    retained = resolve_provider_operation(
        contract={
            "provider": "openai",
            "resolution_mode": "contractual_retention",
            "retention_rule_id": "rule-1",
        },
        provider="openai",
        provider_operation_ref="response_1",
    )
    assert (retained.state, retained.retention_rule_id) == ("retained", "rule-1")

    missing = resolve_provider_operation(
        contract={"provider": "openai", "resolution_mode": "api_delete"},
        provider="openai",
        provider_operation_ref="file-1",
        delete_and_verify={"openai": lambda _ref: True},
    )
    assert missing.error_code == "PROVIDER_OBJECT_REF_INCOMPATIBLE"

    calls: list[str] = []
    deleted = resolve_provider_operation(
        contract={
            "provider": "openai",
            "resolution_mode": "api_delete",
            "provider_object_prefix": "file-",
        },
        provider="openai",
        provider_operation_ref="file-1",
        delete_and_verify={"openai": lambda ref: (calls.append(ref), False)[1]},
    )
    assert calls == ["file-1"]
    assert deleted.state == "failed"
    assert deleted.error_code == "PROVIDER_DELETION_NOT_VERIFIED"


class _NotFound(Exception):
    def __init__(self) -> None:
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": 404},
            "Error": {"Code": "NoSuchKey"},
        }


class _R2:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))

    def head_object(self, *, Bucket: str, Key: str) -> None:
        raise _NotFound()


def test_r2_adapter_hashes_exact_bytes_before_delete(monkeypatch):
    body = b"synthetic-phase1-audio"
    expected = hashlib.sha256(body).hexdigest()
    r2 = _R2()
    monkeypatch.setattr(lab_audio_storage, "_client", lambda: r2)
    monkeypatch.setattr(
        lab_audio_storage, "get_exact_storage_object_bytes",
        lambda _key, *, bucket, storage_provider: body,
    )
    assert lab_audio_storage.delete_verified_lab_audio_object(
        "principal/take.wav", bucket="recordings", storage_provider="r2",
        expected_sha256=expected,
    )
    assert r2.deleted == [("recordings", "principal/take.wav")]

    with pytest.raises(ValueError, match="checksum"):
        lab_audio_storage.delete_verified_lab_audio_object(
            "principal/take.wav", bucket="recordings", storage_provider="r2",
            expected_sha256="0" * 64,
        )
    assert r2.deleted == [("recordings", "principal/take.wav")]


class _UnknownPreflightClient:
    def __init__(self) -> None:
        self.deleted = False

    def table(self, _name):
        return self

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def limit(self, _value):
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        class Result:
            def __init__(self) -> None:
                self.data = [{
                    "id": "target-1", "state": "unknown",
                    "target_kind": "unknown",
                    "target_ref": "catalog:new_table",
                    "metadata": {}, "initial_match_count": 1,
                    "remaining_match_count": None,
                }]

        return Result()

    def delete(self):
        self.deleted = True
        return self


def test_unknown_inventory_prevents_every_destructive_call():
    client = _UnknownPreflightClient()
    database = type("Database", (), {"client": client})()
    DataPurgeOrchestrator(database).resolve_targets("purge-1")
    assert client.deleted is False


def test_empty_subject_coordinate_never_becomes_an_unfiltered_query():
    class _NoQueryClient:
        def table(self, _name):
            raise AssertionError("empty subject selector reached the database")

    database = type("Database", (), {"client": _NoQueryClient()})()
    orchestrator = DataPurgeOrchestrator(database)

    assert orchestrator._rows(
        "snippets", "id", selector="session_id", values=(),
    ) == []


def test_changed_catalog_after_freeze_blocks_execution(monkeypatch):
    database = type("Database", (), {"client": object()})()
    orchestrator = DataPurgeOrchestrator(database)
    monkeypatch.setattr(
        "services.data_purge.dependency_manifest_sha256", lambda: "a" * 64,
    )
    monkeypatch.setattr(
        orchestrator, "_catalog",
        lambda: {"catalog_sha256": "new", "unknown_relations": []},
    )

    with pytest.raises(RuntimeError, match="PURGE_CATALOG_CHANGED_AFTER_FREEZE"):
        orchestrator._assert_frozen_contract({
            "resolver_version": "phase1-purge-resolver-v2",
            "dependency_manifest_sha256": "a" * 64,
            "catalog_sha256": "frozen",
        })


def test_legacy_account_only_take_is_an_explicit_unknown_target(monkeypatch):
    database = type("Database", (), {"client": object()})()
    orchestrator = DataPurgeOrchestrator(database)
    graph = SubjectGraph(
        principal_ids=("principal-1",), user_ids=("user-1",),
        take_ids=("take-legacy",),
        unresolved_legacy_take_ids=("take-legacy",),
    )
    monkeypatch.setattr(
        orchestrator, "_request",
        lambda _request_id: {
            "id": "purge-1", "acquisition_principal_id": "principal-1",
        },
    )
    monkeypatch.setattr(
        orchestrator, "_catalog",
        lambda: {
            "existing_allowlisted_relations": [], "unknown_relations": [],
            "catalog_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(orchestrator, "build_subject_graph", lambda *_args: graph)
    monkeypatch.setattr(orchestrator, "_storage_targets", lambda *_args: [])
    monkeypatch.setattr(orchestrator, "_provider_targets", lambda *_args: [])

    inventory = orchestrator.build_inventory("purge-1")

    unresolved = next(
        target for target in inventory["targets"]
        if target.target_ref == "legacy-take-ownership:unresolved"
    )
    assert unresolved.initial_match_count == 1
    assert (
        unresolved.metadata["reason_code"]
        == "LEGACY_TAKE_OWNER_PRINCIPAL_UNRESOLVED"
    )


def test_already_verified_object_is_not_deleted_twice(monkeypatch):
    calls: list[str] = []
    database = type("Database", (), {"client": object()})()
    orchestrator = DataPurgeOrchestrator(database)
    monkeypatch.setattr(
        orchestrator, "_resolve",
        lambda _target, **kwargs: calls.append(kwargs["state"]),
    )
    monkeypatch.setattr(
        "services.data_purge.verify_lab_audio_object_absent",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "services.data_purge.delete_verified_lab_audio_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("already-purged object reached provider")
        ),
    )
    orchestrator._resolve_object(
        "purge-1",
        {
            "id": "target-1", "initial_match_count": 0,
            "metadata": {"already_purged": True, "sha256": "a" * 64},
        },
        type("Graph", (), {"principal_ids": ("principal-1",)})(),
    )
    assert calls == ["not_found"]


def test_operator_execution_is_disabled_without_exact_double_gate(monkeypatch):
    monkeypatch.delenv("PHASE1_PURGE_EXECUTION_ENABLED", raising=False)
    with pytest.raises(SystemExit, match="PHASE1_PURGE_EXECUTION_DISABLED"):
        run_phase1_data_purge.main([
            "--purge-request-id", "purge-1", "--execute",
            "--confirm-request-id", "purge-1",
        ])

    monkeypatch.setenv("PHASE1_PURGE_EXECUTION_ENABLED", "true")
    with pytest.raises(SystemExit, match="PURGE_REQUEST_CONFIRMATION_MISMATCH"):
        run_phase1_data_purge.main([
            "--purge-request-id", "purge-1", "--execute",
            "--confirm-request-id", "purge-2",
        ])
