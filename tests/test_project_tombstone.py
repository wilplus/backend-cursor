"""The project row is a tombstone in every purge (founder 2026-09-25, N9).

tests/test_take_purge_postgres.py proves it on the real schema; these pin the
Python side without a database.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_registry import (
    dependency_by_code,
)


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


def test_a_take_record_is_wiped_by_the_lineage_function():
    """N12: a take's permanent record goes through its own wipe, and content
    left behind is still a failure."""
    orchestrator, client = _orchestrator({"tombstoned": 3, "not_blank": 0})
    orchestrator._resolve_tombstone(
        _target(), dependency_by_code("canonical_transcript_versions"), 1)
    client.rpc.assert_called_once_with(
        "tombstone_phase1_purge_lineage_v1", {"p_purge_request_id": "r1"})
    assert orchestrator._resolve.call_args.kwargs["state"] == "retained"

    orchestrator, _ = _orchestrator({"tombstoned": 3, "not_blank": 2})
    orchestrator._resolve_tombstone(
        _target(), dependency_by_code("v2_sessions"), 1)
    assert orchestrator._resolve.call_args.kwargs["state"] == "failed"
