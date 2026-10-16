"""The status read on every app open (founder 2026-10-16: it took ~600 ms).

The client reads `pending_deletion` only when the status says blocked and
never reads `pending_project_deletions`, so the two deletion reads run only
for a blocked person, and then side by side. An ordinary open pays the
status read alone.

Then (0473) that one status read is one round trip:
`read_phase1_processing_status_v1` resolves the owner, the acquirer and the
status in a single call. When it cannot (migration not applied, it raises,
or it answers a null principal), the route takes exactly the old path.
"""
from __future__ import annotations

import pytest

from services.canonical_product import OwnerPrincipal
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository


class _Service(ProcessingAuthorizationService):
    def __init__(self, status):
        self._status, self.reads = status, []

    def status(self, principal_id):
        return dict(self._status)

    def pending_deletion(self, principal_id):
        self.reads.append("deletion")
        return {"kind": "account"}

    def pending_project_deletions(self, principal_id):
        self.reads.append("projects")
        return [{"id": "p1"}]


def test_an_ordinary_open_reads_the_status_alone():
    service = _Service({"authorized": True, "code": "OK"})
    out = service.status_with_deletions("principal-1")
    assert service.reads == []
    assert out["pending_deletion"] is None
    assert out["pending_project_deletions"] == []
    assert out["authorized"] is True


def test_a_blocked_person_gets_both_deletions():
    service = _Service({"authorized": False,
                        "code": "PROCESSING_SERVICE_BLOCKED"})
    out = service.status_with_deletions("principal-1")
    assert sorted(service.reads) == ["deletion", "projects"]
    assert out["pending_deletion"] == {"kind": "account"}
    assert out["pending_project_deletions"] == [{"id": "p1"}]


# ── One round trip (0473) ──────────────────────────────────────────────────

ACQUIRER = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"


class _Result:
    def __init__(self, data):
        self.data = data


class _Rpc:
    def __init__(self, client, name, params):
        self.client, self.name, self.params = client, name, params

    def execute(self):
        self.client.calls.append((self.name, self.params))
        if isinstance(self.client.answer, Exception):
            raise self.client.answer
        return _Result(self.client.answer)


class _Client:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def rpc(self, name, params=None):
        return _Rpc(self, name, params)


class _Database:
    def __init__(self, answer):
        self.client = _Client(answer)


def _service(answer, mode="off"):
    return ProcessingAuthorizationService(_Database(answer), mode=mode)


def test_the_fast_path_answers_the_status_with_gate_mode_in_one_call():
    service = _service({"acquisition_principal_id": ACQUIRER,
                        "status": {"authorized": True,
                                   "code": "PROCESSING_AUTHORIZED"}},
                       mode="enforce")
    out = service.status_in_one_trip(USER, None)
    assert out == (ACQUIRER, {"authorized": True,
                              "code": "PROCESSING_AUTHORIZED",
                              "gate_mode": "enforce"})
    assert service.database.client.calls == [(
        "read_phase1_processing_status_v1",
        {"p_user_id": USER, "p_product_owner_principal_id": None})]


def test_a_reacceptance_keeps_its_country_after_gate_mode():
    service = _service({"acquisition_principal_id": ACQUIRER,
                        "status": {"authorized": False,
                                   "code": "PROCESSING_AUTHORIZATION_REQUIRED",
                                   "reacceptance_required": True,
                                   "country_of_residence": "pl"}})
    _, status = service.status_in_one_trip(None, ACQUIRER)
    assert list(status)[-2:] == ["gate_mode", "country_of_residence"]
    assert status["country_of_residence"] == "pl"
    assert status["gate_mode"] == "off"


@pytest.mark.parametrize("answer", [
    RuntimeError("function read_phase1_processing_status_v1 does not exist"),
    {"acquisition_principal_id": None, "status": None},
    None,
    [],
])
def test_the_fast_path_steps_aside_when_it_cannot_vouch(answer):
    assert _service(answer).status_in_one_trip(USER, None) is None


def test_nothing_to_read_by_asks_nothing():
    service = _service({"acquisition_principal_id": ACQUIRER, "status": {}})
    assert service.status_in_one_trip(None, None) is None
    assert service.database.client.calls == []


# ── The route (the real app, through routing) ─────────────────────────────

@pytest.fixture
def old_path(monkeypatch):
    """Today's three-step read, stubbed so a test can see whether it ran."""
    seen: list = []

    def owner_for_user(self, user_id):
        seen.append("owner")
        return OwnerPrincipal("owner-1", str(user_id), False)

    def resolve(self, principal_id, *, user_id=None, recording_id=None):
        seen.append("resolve")
        return ACQUIRER

    def status(self, principal_id):
        seen.append("status")
        return {"authorized": True, "code": "PROCESSING_AUTHORIZED",
                "gate_mode": "off", "read": "in steps"}

    monkeypatch.setattr(ProjectRepository, "owner_for_user", owner_for_user)
    monkeypatch.setattr(ProcessingAuthorizationService,
                        "resolve_acquisition_principal", resolve)
    monkeypatch.setattr(ProcessingAuthorizationService, "status", status)
    return seen


def test_an_open_that_the_one_trip_read_answers_skips_the_steps(
        app_client, stub_verified_user, monkeypatch, old_path):
    stub_verified_user(USER)
    asked: list = []

    def one_trip(self, user_id, product_owner_principal_id):
        asked.append((user_id, product_owner_principal_id))
        return ACQUIRER, {"authorized": True, "code": "PROCESSING_AUTHORIZED",
                          "gate_mode": "off", "read": "in one trip"}

    monkeypatch.setattr(ProcessingAuthorizationService, "status_in_one_trip",
                        one_trip)
    response = app_client.get("/v2/processing-authorization",
                              headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["read"] == "in one trip"
    assert body["pending_deletion"] is None
    assert body["pending_project_deletions"] == []
    assert asked == [(USER, None)]
    assert old_path == []


def test_an_open_the_one_trip_read_cannot_answer_takes_the_old_path(
        app_client, stub_verified_user, monkeypatch, old_path):
    stub_verified_user(USER)
    monkeypatch.setattr(ProcessingAuthorizationService, "status_in_one_trip",
                        lambda self, user_id, principal_id: None)
    response = app_client.get("/v2/processing-authorization",
                              headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    assert response.get_json()["read"] == "in steps"
    assert old_path == ["owner", "resolve", "status"]


def test_a_guest_is_verified_in_python_before_the_one_trip_read(
        app_client, monkeypatch, old_path):
    """The function never sees a token: a guest id reaches it only after
    the stored secret matched. A token that does not verify is refused by
    the old path, as before, and the one-trip read is never asked."""
    asked: list = []
    monkeypatch.setattr(
        ProcessingAuthorizationService, "status_in_one_trip",
        lambda self, user_id, principal_id: asked.append(principal_id))
    monkeypatch.setattr(ProjectRepository, "get_principal",
                        lambda self, principal_id: {
                            "id": principal_id, "user_id": None,
                            "guest_secret_hash": "not-the-hash"})
    response = app_client.get(
        "/v2/processing-authorization",
        headers={"X-Willab-Guest-Owner": f"{ACQUIRER}.{'s' * 40}"})
    assert response.status_code == 403
    assert response.get_json()["code"] == "INVALID_GUEST_OWNER"
    assert asked == []
