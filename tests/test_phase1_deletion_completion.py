"""
STORY    As a speaker who asks for deletion, I want the copies our providers
         hold deleted, or a lawful retention recorded, so that erasure
         completes and never claims more than it did. (Deletion.)
OUTCOME
  O1  A provider copy is reported deleted only when the delete is verified;
      nothing remains.
  O2  A contractual retention is recorded with its rule; without a rule it
      is refused.
  O3  Anything unverified fails closed: wrong provider, unknown mode, an
      object ref outside the contract, an unverified or crashing delete.
  O4  The OpenAI adapter calls a file deleted only when the provider then
      answers "not found" for it.
PROVES   O1 -> test_a_verified_provider_delete_is_deleted
         O2 -> test_a_retention_needs_its_rule
         O3 -> test_provider_deletion_fails_closed
         O4 -> test_the_openai_adapter_checks_the_file_is_really_gone
WHY      Phase-1 deletion completion (0312). The freeze's acceptance of every
         target the orchestrator builds is proven on the database in
         tests/test_account_deletion_starts_postgres.py and
         tests/test_phase1_deletion_completion_postgres.py.
"""
from __future__ import annotations

import types

import pytest

from services.provider_deletion import resolve_provider_operation

API_DELETE = {"provider": "openai", "resolution_mode": "api_delete",
              "provider_object_prefix": "file-"}


def _resolve(contract=API_DELETE, ref="file-1", adapter=lambda _ref: True, provider="openai"):
    return resolve_provider_operation(contract=contract, provider=provider,
                                      provider_operation_ref=ref,
                                      delete_and_verify={"openai": adapter})


def test_a_verified_provider_delete_is_deleted():
    calls: list[str] = []
    result = _resolve(adapter=lambda ref: calls.append(ref) or True)
    assert calls == ["file-1"]
    assert (result.state, result.remaining_match_count, result.error_code) == ("deleted", 0, None)


def test_a_retention_needs_its_rule():
    retained = _resolve(contract={"provider": "openai", "resolution_mode": "contractual_retention",
                                  "retention_rule_id": "rule-1"})
    assert (retained.state, retained.retention_rule_id) == ("retained", "rule-1")
    no_rule = _resolve(contract={"provider": "openai", "resolution_mode": "contractual_retention"})
    assert (no_rule.state, no_rule.error_code) == ("failed", "RETENTION_RULE_REQUIRED")


def _raise(_ref):
    raise TimeoutError("provider down")


@pytest.mark.parametrize("kwargs, code", [
    ({"provider": "anthropic"}, "PROVIDER_CONTRACT_MISMATCH"),
    ({"contract": {"provider": "openai", "resolution_mode": "guess"}}, "UNKNOWN_PROVIDER_MODE"),
    ({"ref": "response_1"}, "PROVIDER_OBJECT_REF_INCOMPATIBLE"),
    ({"contract": {"provider": "openai", "resolution_mode": "api_delete"}},
     "PROVIDER_OBJECT_REF_INCOMPATIBLE"),
    ({"adapter": lambda _ref: False}, "PROVIDER_DELETION_NOT_VERIFIED"),
    ({"adapter": _raise}, "PROVIDER_DELETE_TIMEOUTERROR"),
])
def test_provider_deletion_fails_closed(kwargs, code):
    result = _resolve(**kwargs)
    assert (result.state, result.remaining_match_count, result.error_code) == ("failed", 1, code)


class _NotFound(Exception):
    status_code = 404


@pytest.mark.parametrize("deleted, retrieve_raises, verified", [
    (True, _NotFound(), True),        # deleted, and the provider no longer has it
    (True, None, False),              # "deleted", yet the file is still there
    (False, _NotFound(), False),      # the provider refused the delete
])
def test_the_openai_adapter_checks_the_file_is_really_gone(monkeypatch, deleted,
                                                           retrieve_raises, verified):
    def retrieve(ref):
        if retrieve_raises:
            raise retrieve_raises
        return {"id": ref}

    files = types.SimpleNamespace(delete=lambda ref: types.SimpleNamespace(deleted=deleted),
                                  retrieve=retrieve)
    monkeypatch.setattr("services.openai_service.OpenAIService",
                        lambda: types.SimpleNamespace(client=types.SimpleNamespace(files=files)))
    state = resolve_provider_operation(contract=API_DELETE, provider="openai",
                                       provider_operation_ref="file-1").state
    assert state == ("deleted" if verified else "failed")
