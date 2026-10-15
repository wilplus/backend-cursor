"""A dropped connection is not a refusal (founder 2026-10-15).

A Take sat at 59% for seven minutes because the permit RPC's connection was
closed under it ("Server disconnected") and the worker read that as
"Provider processing is not authorized", failing the attempt. The permit RPC
is idempotent on its key, so it is sent once more; a real denial stays final.
"""
from __future__ import annotations

import httpx
import pytest

from services.processing_authorization import (
    ProcessingAuthorizationError, ProcessingAuthorizationService,
)

PERMIT = {"id": "permit-1", "expires_at": "2999-01-01T00:00:00+00:00"}


class _Call:
    def __init__(self, outcome):
        self.outcome = outcome

    def execute(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return type("R", (), {"data": [self.outcome]})()


class _Client:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.sent = []

    def rpc(self, name, params):
        self.sent.append((name, params["p_idempotency_key"]))
        return _Call(self.outcomes.pop(0))


def _permit(client):
    service = ProcessingAuthorizationService(
        type("Db", (), {"client": client})(), mode="enforce")
    return service.issue_provider_permit(
        acquisition_principal_id="principal-1", take_id="take-1",
        recording_id="rec-1", provider="openai", operation_kind="transcribe",
        minimum_data_manifest={}, idempotency_key="key-1")


def test_a_dropped_connection_is_sent_once_more_with_the_same_key():
    client = _Client(httpx.RemoteProtocolError("Server disconnected"), PERMIT)
    assert _permit(client)["id"] == "permit-1"
    assert client.sent == [("issue_phase1_provider_permit_v1", "key-1")] * 2


def test_a_denial_is_final():
    client = _Client(RuntimeError("PROVIDER_PERMIT_DENIED"), PERMIT)
    with pytest.raises(ProcessingAuthorizationError):
        _permit(client)
    assert len(client.sent) == 1
