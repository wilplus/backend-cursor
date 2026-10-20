"""
STORY    As a speaker, I want a brief database hiccup not to fail my Take, so
         that processing continues instead of sitting at 59%.
OUTCOME
  O1  A dropped connection or a timeout is sent again with the same key
      until it answers.
  O2  A real denial is final and is not sent again.
  O3  A database that never answers gives "unavailable" (503) after a
      bounded number of retries, not "denied".
  O4  The log line for a refusal names the check that failed.
PROVES   O1 -> test_a_dropped_connection_is_sent_once_more_with_the_same_key,
               test_a_statement_timeout_is_resent_with_the_same_key_until_it_answers
         O2 -> test_a_denial_is_final
         O3 -> test_a_database_that_never_answers_is_unavailable_not_a_denial
         O4 -> test_a_refusal_log_line_names_the_check_that_failed
WHY      Founder 2026-10-15: a Take sat at 59% for seven minutes.
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


# ── the database gave no answer at all (founder 2026-10-15, second report) ──
# After the resend above shipped, the same Take failed its first attempt on
# "Provider processing is not authorized." again and passed its second seven
# minutes later. A timeout, a busy pool, a gateway 503 and a cancelled
# statement are not decisions either; they are resent, bounded, and when
# they persist the refusal says "unavailable", not "denied".

import logging  # noqa: E402

from postgrest.exceptions import APIError  # noqa: E402

from services import processing_authorization as pa  # noqa: E402


@pytest.fixture(autouse=True)
def _no_pauses(monkeypatch):
    monkeypatch.setattr(pa, "_sleep", lambda _s: None)


def _statement_timeout():
    return APIError({"message": "canceling statement due to statement timeout",
                     "code": "57014", "hint": None, "details": None})


def test_a_statement_timeout_is_resent_with_the_same_key_until_it_answers():
    client = _Client(_statement_timeout(), httpx.ReadTimeout("read"), PERMIT)
    assert _permit(client)["id"] == "permit-1"
    assert client.sent == [("issue_phase1_provider_permit_v1", "key-1")] * 3


def test_a_database_that_never_answers_is_unavailable_not_a_denial(caplog):
    gateway = APIError({"message": "JSON could not be generated", "code": 503,
                        "hint": "Refer to full message for details",
                        "details": "b'<html>503 Service Unavailable</html>'"})
    client = _Client(*([gateway] * 10))
    with caplog.at_level(logging.WARNING, logger=pa.__name__):
        with pytest.raises(ProcessingAuthorizationError) as caught:
            _permit(client)
    assert caught.value.code == "PROVIDER_PERMIT_UNAVAILABLE"
    assert caught.value.status == 503
    # Bounded: one send plus the resend pauses, never a loop.
    assert len(client.sent) == 1 + len(pa._PERMIT_RESEND_PAUSES_S)


def test_a_refusal_log_line_names_the_check_that_failed(caplog):
    client = _Client(RuntimeError("PROCESSING_SOURCE_PRINCIPAL_MISMATCH"))
    with caplog.at_level(logging.WARNING, logger=pa.__name__):
        with pytest.raises(ProcessingAuthorizationError) as caught:
            _permit(client)
    assert caught.value.code == "PROCESSING_SOURCE_PRINCIPAL_MISMATCH"
    assert caught.value.status == 403
    assert len(client.sent) == 1
    line = next(r.getMessage() for r in caplog.records
                if "provider permit refused" in r.getMessage())
    assert "code=PROCESSING_SOURCE_PRINCIPAL_MISMATCH" in line
    assert "operation=transcribe" in line
    assert "RuntimeError" in line
