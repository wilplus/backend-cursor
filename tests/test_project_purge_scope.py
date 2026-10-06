"""A project purge reaches one project, and every account-keyed table is placed.

The account purge reaches a table through the person (principal, user,
speaker, permit). A project purge's graph lists none of those, so a table
reached only that way would silently keep its rows. So every such registry
entry must be placed by `services/data_purge_project_scope.py` - re-pointed at
the project, left with the account, wiped through its parent, or held - or it
stops the purge for review whenever the account has a row there. These tests
pin the placement, each re-pointed column's existence, and that neither
orchestrator ever runs the other's kind of request.

Run: python3 -m pytest tests/test_project_purge_scope.py
"""
from __future__ import annotations

import sys
import types

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]

import pytest  # noqa: E402

from services import data_purge_project_scope as scope  # noqa: E402
from services.data_purge import DataPurgeOrchestrator  # noqa: E402
from services.data_purge_registry import DEPENDENCIES, dependency_by_code  # noqa: E402
from tests.test_purge_registry_selectors_exist import (  # noqa: E402
    LEGACY_TABLES,
    _definitions,
    _sql,
)

PLACED = (
    set(scope.PROJECT_SELECTORS) | scope.ACCOUNT_LEVEL
    | set(scope.WIPED_WITH_PARENT) | set(scope.PROJECT_HOLDS)
)


def test_every_placed_code_is_a_registry_code():
    assert PLACED <= {dependency.code for dependency in DEPENDENCIES}


def test_no_code_is_placed_twice():
    lists = (
        set(scope.PROJECT_SELECTORS), set(scope.ACCOUNT_LEVEL),
        set(scope.WIPED_WITH_PARENT), set(scope.PROJECT_HOLDS),
    )
    assert sum(len(item) for item in lists) == len(PLACED)


def test_every_deleted_retained_or_tombstoned_account_table_is_placed():
    """Only a separately governed lineage (external_review) may be left to
    the fail-closed count; anything a purge acts on must be placed."""
    unplaced = sorted(
        dependency.code for dependency in DEPENDENCIES
        if dependency.code in scope.account_keyed_codes()
        and dependency.disposition != "external_review"
        and dependency.code not in PLACED
    )
    assert unplaced == []


def test_every_tombstone_reaches_the_project():
    """A tombstone counted zero is never wiped; each must count the project's
    rows, or be wiped and counted through its parent."""
    for dependency in DEPENDENCIES:
        if dependency.disposition != "tombstone":
            continue
        assert (
            dependency.code in scope.PROJECT_SELECTORS
            or dependency.code in scope.WIPED_WITH_PARENT
        ), dependency.code


def test_every_re_pointed_column_exists_in_its_table():
    sql = _sql()
    missing = []
    for code, (column, _locator) in {
            **scope.PROJECT_SELECTORS, **scope.PROJECT_HOLDS}.items():
        dependency = dependency_by_code(code)
        assert dependency is not None
        if dependency.relation in LEGACY_TABLES:
            continue
        found = any(
            column in text for text in _definitions(sql, dependency.relation)
        )
        if not found:
            missing.append(f"{code}: {dependency.relation}.{column}")
    assert missing == []


def test_every_re_pointed_locator_is_one_the_project_graph_fills():
    empty = {"principal", "user", "speaker", "permit"}
    for code, (_column, locator) in {
            **scope.PROJECT_SELECTORS, **scope.PROJECT_HOLDS}.items():
        assert locator not in empty, code


def test_the_parent_of_a_wiped_row_counts_the_project():
    for parent in scope.WIPED_WITH_PARENT.values():
        assert parent in scope.PROJECT_SELECTORS


class _Query:
    def __init__(self, row):
        self._row = row

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        return types.SimpleNamespace(data=[self._row])


class _Client:
    def __init__(self, row):
        self._row = row

    def table(self, _name):
        return _Query(self._row)

    def rpc(self, *_a, **_k):
        raise AssertionError("no scope may reach the database past the check")


def _database(row):
    return types.SimpleNamespace(client=_Client(row))


def test_the_account_orchestrator_refuses_a_project_request():
    database = _database({
        "id": "purge-1", "acquisition_principal_id": "principal-1",
        "trigger_kind": "project_deletion", "state": "requested",
        "project_id": "project-1",
    })
    with pytest.raises(RuntimeError, match="PURGE_SCOPE_MISMATCH"):
        DataPurgeOrchestrator(database).build_inventory("purge-1")


def test_the_project_orchestrator_refuses_an_account_request():
    database = _database({
        "id": "purge-1", "acquisition_principal_id": "principal-1",
        "trigger_kind": "account_deletion", "state": "requested",
        "project_id": None,
    })
    with pytest.raises(RuntimeError, match="PURGE_NOT_A_PROJECT_DELETION"):
        scope.ProjectPurgeOrchestrator(database).build_inventory("purge-1")


def test_the_runner_picks_the_orchestrator_by_kind():
    project = _database({"trigger_kind": "project_deletion"})
    account = _database({"trigger_kind": "account_deletion"})
    assert type(scope.orchestrator_for(project, "p")) is scope.ProjectPurgeOrchestrator
    assert type(scope.orchestrator_for(account, "a")) is DataPurgeOrchestrator


def test_the_project_scope_has_its_own_resolver_and_freeze():
    assert scope.ProjectPurgeOrchestrator.resolver_version == (
        "phase1-project-purge-resolver-v1")
    assert scope.ProjectPurgeOrchestrator.freeze_function == (
        "freeze_phase1_project_purge_inventory_v1")
    assert DataPurgeOrchestrator.resolver_version == "phase1-purge-resolver-v4"
    assert scope.project_placement_sha256() != (
        DataPurgeOrchestrator(_database({}))._dependency_manifest_sha())
