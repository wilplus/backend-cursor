from __future__ import annotations

import re
from pathlib import Path

from services.data_purge import DataPurgeOrchestrator, SubjectGraph
from services.data_purge_registry import (
    DEPENDENCIES,
)
from services.provider_deletion import resolve_provider_operation


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


def test_every_dependency_target_kind_is_one_the_freeze_accepts():
    """0362. The freeze files any other kind as `unknown`, and one unknown
    target stops the whole erasure — fourteen registry entries did that at
    zero rows. The orchestrator's accepted set must be the SQL's, and every
    dependency target it builds must use it."""
    from services.data_purge import FREEZE_TARGET_KINDS

    root = Path(__file__).resolve().parent.parent
    text = (root / "migrations" / "an_account_deletion_can_start.sql").read_text(
        encoding="utf-8")
    body = text[text.index(
        "CREATE OR REPLACE FUNCTION public.freeze_phase1_purge_inventory_v4("):]
    listed = body[body.index("IF kind NOT IN ("):body.index(") THEN kind := 'unknown'")]
    assert set(re.findall(r"'([a-z0-9_]+)'", listed)) == FREEZE_TARGET_KINDS

    orchestrator = DataPurgeOrchestrator(type("Database", (), {"client": object()})())
    orchestrator._count = lambda *_args: 0
    graph = SubjectGraph(principal_ids=("principal-1",))
    relations = frozenset(dependency.relation for dependency in DEPENDENCIES)
    for dependency in DEPENDENCIES:
        target = orchestrator._dependency_target(dependency, graph, relations)
        assert target is not None and target.target_kind in FREEZE_TARGET_KINDS, (
            dependency.code, target)
