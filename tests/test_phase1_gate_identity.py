"""
STORY    As a signed-in speaker, I want the consent gate to recognise me, and
         as a new guest to get an identity it accepts, so that I am not met
         with "A verified owner is required." on every screen. (Consent gate
         in front of record: nothing reaches processing without it.)
OUTCOME
  O1  A bearer user passes the enforced gate as themselves (the gate
      resolves that user's principal, and authorizes core service for it).
  O2  A fresh guest is refused, mints a guest token, and then passes as
      that new principal.
PROVES   O1 -> test_a_signed_in_speaker_passes_the_gate_as_themselves
         O2 -> test_a_first_time_guest_mints_an_identity_the_gate_then_accepts
WHY      2026-09-21 401 storm: the before_request gate ran before the view's
         auth decorator and saw every caller as anonymous (#422/#425/#427).
         The REAL app runs through routing; only token verification and the
         ownership/authority reads are stubbed.
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

    def require_current(self, acquisition_principal_id, *, operation,
                        status=None):
        seen["authorized"] = (acquisition_principal_id, operation)
        return {"authorized": True}

    # The one-trip read (0473) steps aside, so the step-by-step identity
    # decision below is what runs.
    monkeypatch.setattr(
        ProcessingAuthorizationService, "status_in_one_trip",
        lambda self, user_id, principal_id: None,
    )
    monkeypatch.setattr(ProjectRepository, "owner_for_user", owner_for_user)
    monkeypatch.setattr(
        ProcessingAuthorizationService, "resolve_acquisition_principal",
        resolve_acquisition_principal,
    )
    monkeypatch.setattr(
        ProcessingAuthorizationService, "require_current", require_current,
    )
    return seen


def test_a_signed_in_speaker_passes_the_gate_as_themselves(
    app_client, enforced, stubbed_authority, stub_verified_user,
):
    stub_verified_user("user-1")
    passed = app_client.get("/v2/chat/session-state",
                            headers={"Authorization": "Bearer signed-in"})
    assert (passed.get_json() or {}).get("error") != OWNER_REQUIRED
    assert stubbed_authority.get("user_id") == "user-1"
    assert stubbed_authority.get("authorized") == ("owner-1", "core_service")


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
