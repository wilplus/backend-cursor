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


def test_a_first_time_guest_mints_an_identity_the_gate_then_accepts(
    app_client, monkeypatch, enforced, stubbed_authority,
):
    """F1 Repair Plan Phase 0.5 (2026-10-03). A brand-new guest met
    OWNER_REQUIRED on every core route, project creation included, because
    nothing ever called the mint below. The mint sits outside the gate, and
    the token it issues is what the gate resolves the guest by."""
    principals: dict = {}

    def create_guest_owner(self, principal_id, secret_hash):
        principals[str(principal_id)] = {
            "id": str(principal_id), "user_id": None,
            "guest_secret_hash": secret_hash}
        return OwnerPrincipal(str(principal_id), None, True)

    monkeypatch.setattr(ProjectRepository, "create_guest_owner", create_guest_owner)
    monkeypatch.setattr(
        ProjectRepository, "get_principal",
        lambda self, principal_id: principals.get(str(principal_id)))

    # Before the mint: the closed loop the visitor met.
    refused = app_client.get("/v2/chat/session-state")
    assert (refused.get_json() or {}).get("error") == OWNER_REQUIRED

    minted = app_client.post("/v2/processing-authorization/principal")
    assert minted.status_code == 201
    body = minted.get_json() or {}
    token = body.get("guest_owner_token")
    assert token and body.get("is_guest") is True

    passed = app_client.get(
        "/v2/chat/session-state",
        headers={"X-Willab-Guest-Owner": token},
    )
    assert (passed.get_json() or {}).get("error") != OWNER_REQUIRED
    assert stubbed_authority.get("authorized") == (
        body["owner_principal_id"], "core_service")
