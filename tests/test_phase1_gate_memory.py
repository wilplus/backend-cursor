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

    # The one-trip read (0473) steps aside, so `require_current` below is
    # the one place the authority is asked.
    monkeypatch.setattr(ProcessingAuthorizationService, "status_in_one_trip",
                        lambda self, user_id, principal_id: None)

    def require_current(self, principal_id, *, operation, status=None):
        state["asked"] += 1
        if state["refuse"]:
            raise ProcessingAuthorizationError(
                "PROCESSING_AUTHORIZATION_REQUIRED", "required", 403)
        return {"authorized": True}

    monkeypatch.setattr(ProcessingAuthorizationService, "require_current",
                        require_current)
    return state


def test_a_write_always_asks(app_client, gate):
    app_client.get(READ, headers=BEARER)
    app_client.post(WRITE, headers=BEARER, json={})
    app_client.post(WRITE, headers=BEARER, json={})
    assert gate["asked"] == 3
