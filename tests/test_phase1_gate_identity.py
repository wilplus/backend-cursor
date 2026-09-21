"""The Phase-1 gate must see the signed-in user (founder's evening, 2026-09-21).

`enforce_phase1_processing_gate` is a `before_request` hook. `request.user_id`
is set by the view's `@optional_auth` / `@require_auth` decorator, and a view's
decorators run AFTER `before_request`. So the gate saw every caller as
anonymous, and with PLF1_PROCESSING_AUTHORIZATION_MODE=enforce every core route
answered 401 "A verified owner is required." to a signed-in founder — the 401
storm that #422/#425/#427 chased through the frontend's token renewal.

These run the REAL app through routing, so the ordering that caused the defect
is the ordering under test. Token verification is stubbed the way every other
route test stubs it; the ownership and authority lookups are stubbed so the
gate's identity decision is the only thing on trial.
"""
from __future__ import annotations

import pytest

from routes.v2 import processing_authorization as gate_module
from services.canonical_product import OwnerPrincipal
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository


OWNER_REQUIRED = "A verified owner is required."


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")


@pytest.fixture
def stubbed_authority(monkeypatch):
    """Ownership and authority answer for whoever the gate says is calling.

    `seen` records the user the gate resolved, so a test can assert the gate
    identified the bearer rather than merely that the request got through.
    """
    seen: dict = {}

    def owner_for_user(self, user_id):
        seen["user_id"] = str(user_id)
        return OwnerPrincipal("owner-1", str(user_id), False)

    def resolve_acquisition_principal(self, principal_id, *, user_id=None,
                                      recording_id=None):
        seen["principal_id"] = principal_id
        return principal_id

    def require_current(self, acquisition_principal_id, *, operation):
        seen["authorized"] = (acquisition_principal_id, operation)
        return {"authorized": True}

    monkeypatch.setattr(ProjectRepository, "owner_for_user", owner_for_user)
    monkeypatch.setattr(
        ProcessingAuthorizationService, "resolve_acquisition_principal",
        resolve_acquisition_principal,
    )
    monkeypatch.setattr(
        ProcessingAuthorizationService, "require_current", require_current,
    )
    return seen


def test_gate_sees_the_bearer_before_the_view_decorator_runs(
    app_client, stub_verified_user, enforced, stubbed_authority,
):
    stub_verified_user("user-1")
    response = app_client.get(
        "/v2/chat/session-state",
        headers={"Authorization": "Bearer signed-in"},
    )
    body = response.get_json() or {}
    # The old gate raised INVALID_GUEST_OWNER here without ever asking who
    # owned the token.
    assert body.get("error") != OWNER_REQUIRED
    assert stubbed_authority.get("user_id") == "user-1"
    assert stubbed_authority.get("authorized") == ("owner-1", "core_service")


def test_gate_still_refuses_an_anonymous_caller_with_no_guest_token(
    app_client, enforced, stubbed_authority,
):
    response = app_client.get("/v2/chat/session-state")
    assert response.status_code == 401
    assert (response.get_json() or {}).get("error") == OWNER_REQUIRED
    assert "user_id" not in stubbed_authority


def test_gate_treats_a_rejected_token_as_anonymous_like_optional_auth_does(
    app_client, monkeypatch, enforced, stubbed_authority,
):
    import auth

    def reject(_token):
        raise Exception("Token expired")

    monkeypatch.setattr(auth, "verify_supabase_token", reject)
    response = app_client.get(
        "/v2/chat/session-state",
        headers={"Authorization": "Bearer stale"},
    )
    assert response.status_code == 401
    assert (response.get_json() or {}).get("error") == OWNER_REQUIRED


def test_request_user_id_prefers_what_a_decorator_already_resolved(
    stub_verified_user,
):
    import app as app_module

    stub_verified_user("from-token")
    with app_module.app.test_request_context(
        "/v2/projects", headers={"Authorization": "Bearer x"},
    ):
        from flask import request

        request.user_id = "from-decorator"
        assert gate_module._request_user_id() == "from-decorator"
    with app_module.app.test_request_context(
        "/v2/projects", headers={"Authorization": "Bearer x"},
    ):
        assert gate_module._request_user_id() == "from-token"
    with app_module.app.test_request_context("/v2/projects"):
        assert gate_module._request_user_id() is None
