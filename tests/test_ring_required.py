"""@ring_required(feature): the route boundary of the rings (0394).

Generalised from mlc3_service_required. The order it must keep: building
switch, principal, the ring check, then (unchanged) the MLC-3 enrollment
wristband whose coordinates the service RPCs read. Every refusal is 404.
"""
from __future__ import annotations

import pytest
from flask import Flask, jsonify, request

from routes import phase2_guard
from services import coach_guidance_delivery, rings
from services import db as db_module


P1 = "11111111-1111-4111-8111-111111111111"
ENROLLMENT = {"id": "enr-1", "rollout_revision_id": "rev-1",
              "operation_mode": "cohort_service"}


@pytest.fixture
def app():
    app = Flask(__name__)

    @app.route("/gated")
    @phase2_guard.ring_required("exercise_service")
    def gated():
        return jsonify({
            "ok": True,
            "principal": request.mlc3_principal_id,
            "enrollment": request.mlc3_enrollment_revision_id,
            "mode": request.mlc3_operation_mode,
            "feature": request.ring_feature,
        }), 200

    @app.route("/bundles")
    @phase2_guard.ring_required("confident_moment_bundles")
    def bundles():
        return jsonify({"feature": request.ring_feature}), 200

    return app


@pytest.fixture
def wiring(monkeypatch):
    state = {"switch": True, "principal": {"id": P1}, "on": {"exercise_service": True,
             "confident_moment_bundles": False}, "enrollment": ENROLLMENT, "asked": []}
    monkeypatch.setattr(coach_guidance_delivery, "runtime_is_enabled", lambda: state["switch"])
    monkeypatch.setattr(db_module.db, "get_owner_principal_for_user",
                        lambda user_id: state["principal"])

    def feature_is_on(feature, principal_id, **_):
        state["asked"].append((feature, principal_id))
        return bool(state["on"].get(feature))

    monkeypatch.setattr(rings, "feature_is_on", feature_is_on)
    monkeypatch.setattr(db_module.first_client_repository, "ensure_service_enrollment",
                        lambda **kwargs: state["enrollment"])
    return state


def _call(app, path="/gated", user_id="user-1"):
    with app.test_request_context(path):
        if user_id is not None:
            request.user_id = user_id
        endpoint = app.view_functions[path.strip("/")]
        response, status = endpoint()
        return status, response.get_json()


def test_a_reached_person_passes_and_keeps_the_mlc3_wristband(app, wiring):
    status, body = _call(app)
    assert status == 200
    assert body == {"ok": True, "principal": P1, "enrollment": "enr-1",
                    "mode": "cohort_service", "feature": "exercise_service"}
    assert wiring["asked"] == [("exercise_service", P1)]


def test_the_ring_says_no_is_404(app, wiring):
    wiring["on"]["exercise_service"] = False
    status, body = _call(app)
    assert (status, body) == (404, {"code": "NOT_FOUND"})


def test_each_route_asks_about_its_own_row(app, wiring):
    status, _ = _call(app, "/bundles")
    assert status == 404
    wiring["on"]["confident_moment_bundles"] = True
    status, body = _call(app, "/bundles")
    assert (status, body["feature"]) == (200, "confident_moment_bundles")
    assert ("confident_moment_bundles", P1) in wiring["asked"]


def test_the_building_switch_still_comes_first(app, wiring):
    wiring["switch"] = False
    status, _ = _call(app)
    assert status == 404
    assert wiring["asked"] == []  # the code never reached the check


def test_no_principal_is_404_before_the_check(app, wiring):
    wiring["principal"] = None
    status, _ = _call(app)
    assert status == 404
    assert wiring["asked"] == []
    wiring["principal"] = {"id": P1}
    status, _ = _call(app, user_id=None)
    assert status == 404


def test_enrollment_still_gates_after_the_ring(app, wiring):
    wiring["enrollment"] = None
    status, _ = _call(app)
    assert status == 404
    assert wiring["asked"] == [("exercise_service", P1)]


def test_the_old_name_is_the_exercise_service_row():
    assert phase2_guard.mlc3_pilot_required is phase2_guard.mlc3_service_required
    source = open(phase2_guard.__file__, encoding="utf-8").read()
    assert 'mlc3_service_required = ring_required("exercise_service")' in source


def test_every_runtime_caller_names_its_row():
    from pathlib import Path

    root = Path(phase2_guard.__file__).resolve().parents[1]
    service = (root / "routes" / "v2" / "mlc3_first_client_service.py").read_text()
    bundles = (root / "routes" / "v2" / "confident_moment_bundles.py").read_text()
    assert "@mlc3_service_required" not in service
    assert "@mlc3_service_required" not in bundles
    assert service.count('@ring_required("exercise_service")') == 17
    assert bundles.count('@ring_required("confident_moment_bundles")') == 7
    assert bundles.count('@ring_required("rooting_coverage")') == 1
