"""The core gate remembers a YES for a few seconds, and nothing else (S1,
2026-10-08).

With PLF1_PROCESSING_AUTHORIZATION_MODE=enforce, every core request resolved
the caller's principal and asked the database for current authority: about
three queries before every Ideal Text read. A read-only request may now reuse
a YES this process got for the same caller within GATE_CACHE_SECONDS. A
refusal is never remembered, a write always asks, and every authority or
consent write in this process forgets everything.
"""
from __future__ import annotations

import pytest

from services import processing_authorization as pa
from services.canonical_product import OwnerPrincipal
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)
from services.project_repository import ProjectRepository

READ = "/v2/explore/arc/arc-1/part-histories"
WRITE = "/v2/explore/arc/arc-1/prior-take/decide"
BEARER = {"Authorization": "Bearer signed-in"}


@pytest.fixture
def gate(monkeypatch, swap_db_client, stub_verified_user):
    """The real app, the gate enforced, and the authority answer scripted.
    `asked` counts how often the database's authority was consulted."""
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    stub_verified_user("user-1")
    state = {"asked": 0, "refuse": False}

    monkeypatch.setattr(ProjectRepository, "owner_for_user",
                        lambda self, uid: OwnerPrincipal("owner-1", str(uid), False))
    monkeypatch.setattr(ProcessingAuthorizationService,
                        "resolve_acquisition_principal",
                        lambda self, pid, *, user_id=None, recording_id=None: pid)

    def require_current(self, principal_id, *, operation):
        state["asked"] += 1
        if state["refuse"]:
            raise ProcessingAuthorizationError(
                "PROCESSING_AUTHORIZATION_REQUIRED", "required", 403)
        return {"authorized": True}

    monkeypatch.setattr(ProcessingAuthorizationService, "require_current",
                        require_current)
    return state


def _refused(response):
    body = response.get_json(silent=True) or {}
    return response.status_code == 403 and \
        body.get("code") == "PROCESSING_AUTHORIZATION_REQUIRED"


def test_a_read_reuses_a_recent_yes(app_client, gate):
    app_client.get(READ, headers=BEARER)
    app_client.get(READ, headers=BEARER)
    assert gate["asked"] == 1


def test_a_refusal_is_never_remembered(app_client, gate):
    gate["refuse"] = True
    assert _refused(app_client.get(READ, headers=BEARER))
    assert _refused(app_client.get(READ, headers=BEARER))
    assert gate["asked"] == 2


def test_a_write_always_asks(app_client, gate):
    app_client.get(READ, headers=BEARER)
    app_client.post(WRITE, headers=BEARER, json={})
    app_client.post(WRITE, headers=BEARER, json={})
    assert gate["asked"] == 3


def test_a_consent_write_forgets_the_yes(app_client, gate, monkeypatch):
    app_client.get(READ, headers=BEARER)

    class _Rpc:
        def execute(self):
            return type("R", (), {"data": [{"sensitive_information": False}]})()

    service = ProcessingAuthorizationService.__new__(ProcessingAuthorizationService)
    service.client = type("C", (), {"rpc": lambda _s, *_a: _Rpc()})()
    service.set_consent_choice("owner-1", choice=pa.SENSITIVE_INFORMATION,
                               enabled=False, idempotency_key="key-12345",
                               client_version=None)
    # Revoked in the meantime: the next read asks, and is refused.
    gate["refuse"] = True
    assert _refused(app_client.get(READ, headers=BEARER))
    assert gate["asked"] == 2


def test_a_failed_consent_write_forgets_too():
    key = pa.gate_cache_key("enforce", "user-1", None)
    pa.remember_gate_passed(key, pa.gate_cache_generation())
    service = ProcessingAuthorizationService.__new__(ProcessingAuthorizationService)
    with pytest.raises(ProcessingAuthorizationError):
        service.set_consent_choice("owner-1", choice="nonsense", enabled=True,
                                   idempotency_key="key-12345",
                                   client_version=None)
    assert pa.gate_recently_passed(key) is False


def test_every_authority_write_forgets():
    for name in ("accept", "set_consent_choice", "request_purge",
                 "request_account_deletion", "cancel_account_deletion",
                 "request_data_right"):
        method = getattr(ProcessingAuthorizationService, name)
        assert getattr(method, "__wrapped__", None) is not None, name


def test_a_guest_claim_forgets(monkeypatch):
    key = pa.gate_cache_key("enforce", None, "guest-token")
    pa.remember_gate_passed(key, pa.gate_cache_generation())

    class _Db:
        def claim_guest_owner_principal(self, *_a):
            return {"id": "owner-1"}

    ProjectRepository(_Db()).claim_guest("p", "h", "u")
    assert pa.gate_recently_passed(key) is False


def test_callers_do_not_share_a_yes():
    mine = pa.gate_cache_key("enforce", "user-1", None)
    theirs = pa.gate_cache_key("enforce", "user-2", None)
    guest = pa.gate_cache_key("enforce", None, "token")
    pa.remember_gate_passed(mine, pa.gate_cache_generation())
    assert pa.gate_recently_passed(mine) is True
    assert pa.gate_recently_passed(theirs) is False
    assert pa.gate_recently_passed(guest) is False
    assert pa.gate_cache_key("enforce", None, None) is None
    assert pa.gate_recently_passed(None) is False


def test_a_yes_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(pa.time, "monotonic", lambda: now[0])
    key = pa.gate_cache_key("enforce", "user-1", None)
    pa.remember_gate_passed(key, pa.gate_cache_generation())
    now[0] += pa.GATE_CACHE_SECONDS - 0.1
    assert pa.gate_recently_passed(key) is True
    now[0] += 0.2
    assert pa.gate_recently_passed(key) is False
    assert pa.GATE_CACHE_SECONDS <= 5


def test_a_yes_asked_across_a_write_is_not_kept():
    key = pa.gate_cache_key("enforce", "user-1", None)
    generation = pa.gate_cache_generation()
    pa.clear_gate_cache()  # an authority write lands while the gate asks
    pa.remember_gate_passed(key, generation)
    assert pa.gate_recently_passed(key) is False
