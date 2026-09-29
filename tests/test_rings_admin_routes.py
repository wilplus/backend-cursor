"""/v2/admin/rings/* and /v2/user/rings: thin routes over services/rings.py.

Each route validates, calls one service function, serialises. The admin
routes are gated by @require_admin exactly like the other admin routes; the
user routes by @require_auth. Tested through the unwrapped handlers with the
service faked, the way tests/test_consent_endpoint.py does.
"""
from __future__ import annotations

import pytest
from flask import Flask, request

from routes.v2 import rings as route
from services import rings

P1 = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def app():
    return Flask(__name__)


def _invoke(app, handler, path, method="GET", body=None, query="", **kwargs):
    with app.test_request_context(f"{path}{query}", method=method, json=body):
        request.user_id = "admin-user"
        request.token_payload = {"sub": "admin-user", "email": "artur@willonski.com"}
        response, status = handler.__wrapped__(**kwargs)
        return status, response.get_json()


def test_every_admin_route_is_founder_gated_like_the_other_admin_routes():
    source = open(route.__file__, encoding="utf-8").read()
    admin_routes = source.count('@v2_bp.route("/admin/rings/')
    assert admin_routes == 12
    assert source.count("\n@require_admin\n") == admin_routes
    user_routes = source.count('@v2_bp.route("/user/rings')
    assert user_routes == 2
    assert source.count("\n@require_auth\n") == user_routes


def test_set_feature_passes_the_body_and_the_actor(app, monkeypatch):
    seen = {}

    def set_feature_ring(feature, body, *, changed_by):
        seen.update(feature=feature, body=body, changed_by=changed_by)
        return {"feature": feature, "min_ring": body["min_ring"]}

    monkeypatch.setattr(rings, "set_feature_ring", set_feature_ring)
    status, payload = _invoke(app, route.v2_admin_rings_set_feature,
                              "/v2/admin/rings/features/exercise_service_ui",
                              method="PUT", body={"min_ring": 4, "note": "n"},
                              feature="exercise_service_ui")
    assert status == 200
    assert payload == {"feature": {"feature": "exercise_service_ui", "min_ring": 4}}
    assert seen == {"feature": "exercise_service_ui", "body": {"min_ring": 4, "note": "n"},
                    "changed_by": "user:admin-user"}


def test_a_refused_write_answers_the_rpcs_code_and_status(app, monkeypatch):
    def refuse(feature, killed, *, changed_by):
        raise rings.RingsError("RING_ONE_WAY_KILLED", 409)

    monkeypatch.setattr(rings, "kill_feature", refuse)
    status, payload = _invoke(app, route.v2_admin_rings_kill_feature,
                              "/v2/admin/rings/features/x/kill", method="POST",
                              body={"killed": False}, feature="x")
    assert (status, payload) == (409, {"code": "RING_ONE_WAY_KILLED"})


def test_an_unreachable_ring_table_is_503_with_no_new_copy(app, monkeypatch):
    def down(*a, **k):
        raise rings.RingsError("RINGS_UNAVAILABLE", 503)

    monkeypatch.setattr(rings, "set_default_ring", down)
    status, payload = _invoke(app, route.v2_admin_rings_set_default,
                              "/v2/admin/rings/default", method="PUT", body={"ring": 3})
    assert status == 503 and payload["code"] == "RINGS_UNAVAILABLE"


def test_a_non_object_body_is_400(app, monkeypatch):
    monkeypatch.setattr(rings, "set_principal_ring", lambda *a, **k: pytest.fail("not reached"))
    status, payload = _invoke(app, route.v2_admin_rings_set_person,
                              f"/v2/admin/rings/people/{P1}", method="PUT", body=[1],
                              principal_id=P1)
    assert status == 400 and payload["code"] == "INVALID_INPUT"


def test_people_listing_forwards_search_filters_and_paging(app, monkeypatch):
    seen = {}

    def list_people(**kwargs):
        seen.update(kwargs)
        return {"people": [], "default_ring": 2, "has_more": False}

    monkeypatch.setattr(rings, "list_people", list_people)
    status, payload = _invoke(app, route.v2_admin_rings_people, "/v2/admin/rings/people",
                              query="?search=ola&region=PL&plan=pro&ring=3&limit=20&offset=40")
    assert status == 200 and payload["people"] == []
    assert seen["search"] == "ola" and seen["ring"] == 3
    assert seen["limit"] == 20 and seen["offset"] == 40
    assert seen["filters"]["region"] == "PL" and seen["filters"]["plan"] == "pro"
    assert seen["filters"]["language"] == ""
    status, payload = _invoke(app, route.v2_admin_rings_people, "/v2/admin/rings/people",
                              query="?limit=0")
    assert status == 400


def test_bulk_and_default_and_announcement_routes_call_their_service_function(app, monkeypatch):
    calls = []
    monkeypatch.setattr(rings, "set_principal_rings_bulk",
                        lambda ids, ring, *, changed_by: calls.append(("bulk", ids, ring)) or {"moved": len(ids)})
    monkeypatch.setattr(rings, "set_default_ring",
                        lambda ring, *, changed_by: calls.append(("default", ring)) or {"value": ring})
    monkeypatch.setattr(rings, "set_announcement",
                        lambda feature, body, *, changed_by: calls.append(("announce", feature)) or {"feature": feature})
    status, payload = _invoke(app, route.v2_admin_rings_set_people_bulk, "/v2/admin/rings/people/bulk",
                              method="POST", body={"principal_ids": [P1], "ring": 4})
    assert (status, payload) == (200, {"moved": 1})
    status, payload = _invoke(app, route.v2_admin_rings_set_default, "/v2/admin/rings/default",
                              method="PUT", body={"ring": 3})
    assert (status, payload["default_ring"]) == (200, 3)
    status, _ = _invoke(app, route.v2_admin_rings_set_announcement,
                        "/v2/admin/rings/announcements/exercise_service", method="PUT",
                        body={"title": "[founder copy] t", "body": "[founder copy] b"},
                        feature="exercise_service")
    assert status == 200
    assert [c[0] for c in calls] == ["bulk", "default", "announce"]


def test_user_read_is_no_store_and_never_fatal(app, monkeypatch):
    monkeypatch.setattr(rings, "features_on_for_user", lambda user_id: {
        "features_on": [], "pending_announcements": [], "unavailable": True})
    with app.test_request_context("/v2/user/rings"):
        request.user_id = "user-1"
        response, status = route.v2_user_rings.__wrapped__()
    assert status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["unavailable"] is True


def test_user_decision_records_an_answer_only(app, monkeypatch):
    seen = {}
    monkeypatch.setattr(rings, "principal_for_user", lambda user_id: P1)
    monkeypatch.setattr(rings, "record_announcement_decision",
                        lambda principal, feature, decision: seen.update(
                            principal=principal, feature=feature, decision=decision) or {"decision": decision})
    with app.test_request_context("/v2/user/rings/announcements/exercise_service/decision",
                                  method="POST", json={"decision": "not_now"}):
        request.user_id = "user-1"
        response, status = route.v2_user_rings_announcement_decision.__wrapped__(
            feature="exercise_service")
    assert status == 200
    assert seen == {"principal": P1, "feature": "exercise_service", "decision": "not_now"}
    source = open(route.__file__, encoding="utf-8").read()
    for forbidden in ("accept_mlc2_founder_consent", "set_consent_choice", "ml_consent"):
        assert forbidden not in source
