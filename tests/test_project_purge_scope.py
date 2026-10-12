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


def test_the_project_orchestrator_refuses_an_account_request():
    database = _database({
        "id": "purge-1", "acquisition_principal_id": "principal-1",
        "trigger_kind": "account_deletion", "state": "requested",
        "project_id": None,
    })
    with pytest.raises(RuntimeError, match="PURGE_NOT_A_PROJECT_DELETION"):
        scope.ProjectPurgeOrchestrator(database).build_inventory("purge-1")
