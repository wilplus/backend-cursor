"""The project row is a tombstone in every purge (founder 2026-09-25, N9).

tests/test_take_purge_postgres.py proves it on the real schema; these pin the
Python side without a database.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_registry import DEPENDENCIES, dependency_by_code


def test_projects_is_a_tombstone_under_the_deletion_evidence_rule():
    projects = dependency_by_code("projects")
    assert projects is not None
    assert projects.disposition == "tombstone"
    assert projects.retention_category == "deletion_evidence"
    assert [d.code for d in DEPENDENCIES if d.disposition == "tombstone"] == [
        "projects"]


def _orchestrator(rpc_data=None, rpc_error=None):
    client = MagicMock()
    if rpc_error is not None:
        client.rpc.return_value.execute.side_effect = rpc_error
    else:
        client.rpc.return_value.execute.return_value = SimpleNamespace(
            data=rpc_data)
    orchestrator = DataPurgeOrchestrator(SimpleNamespace(client=client))
    orchestrator._resolve = MagicMock()
    return orchestrator, client


def _target():
    return {"id": "t1", "purge_request_id": "r1", "initial_match_count": 1,
            "metadata": {"dependency_code": "projects",
                         "retention_rule_id": "rule-1"}}


def test_a_blank_tombstone_is_retained_under_the_rule():
    orchestrator, client = _orchestrator({"tombstoned": 1, "not_blank": 0})
    orchestrator._resolve_tombstone(_target(), dependency_by_code("projects"), 1)
    client.rpc.assert_called_once_with(
        "tombstone_phase1_purge_projects_v1", {"p_purge_request_id": "r1"})
    kwargs = orchestrator._resolve.call_args.kwargs
    assert kwargs["state"] == "retained"
    assert kwargs["retention_rule_id"] == "rule-1"


def test_content_left_behind_is_a_failure_not_a_retention():
    orchestrator, _ = _orchestrator({"tombstoned": 1, "not_blank": 1})
    orchestrator._resolve_tombstone(_target(), dependency_by_code("projects"), 1)
    assert orchestrator._resolve.call_args.kwargs["state"] == "failed"


def test_a_failed_wipe_is_a_failure():
    orchestrator, _ = _orchestrator(rpc_error=RuntimeError("boom"))
    orchestrator._resolve_tombstone(_target(), dependency_by_code("projects"), 1)
    assert orchestrator._resolve.call_args.kwargs["state"] == "failed"
