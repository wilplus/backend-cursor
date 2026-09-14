"""API gate and denylist tests for Confident Moment Bundle (Chunk 3)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from flask import Flask, request

from config import Config


def test_config_gates_default_false():
    assert Config.CONFIDENT_MOMENT_BUNDLE_V1_ENABLED is False
    assert Config.ROOTING_COVERAGE_V1_ENABLED is False
    assert Config.MLC2_DATASET_RELEASES_ENABLED is False
    assert Config.MLC2_TRAINING_ENABLED is False
    assert Config.MLC2_PROMOTION_ENABLED is False


def test_runtime_helper_matches_config():
    from services.confident_moment_bundle import runtime_is_enabled
    assert runtime_is_enabled() is False


def _app() -> Flask:
    app = Flask(__name__)
    app.testing = True
    return app


def _raw(handler):
    return handler.__wrapped__.__wrapped__.__wrapped__


def test_disabled_route_stops_before_auth_or_database():
    import routes.v2.confident_moment_bundles as route

    with _app().test_request_context("/v2/x"):
        response, status = route.list_confident_moment_bundles("unused")
    assert status == 404
    assert response.get_json()["code"] == "CONFIDENT_MOMENT_BUNDLE_DISABLED"


def test_get_passes_through_database_projection(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    projection = {"contract_version": "confident-moment-coaching-bundle-v2"}
    envelope = {
        "bundle_projection": projection,
        "confident_moment_summary": {"contract_version": "confident-moment-core-summary-v1"},
    }
    monkeypatch.setattr(route, "load_confident_moment_projection", lambda *_: envelope)
    with _app().test_request_context("/v2/x?take_id=00000000-0000-0000-0000-000000000002"):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        response = _raw(route.list_confident_moment_bundles)(
            "00000000-0000-0000-0000-000000000001"
        )
    assert response.get_json() == projection


def test_v2_coach_render_passes_exact_attachment_and_revision(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    receipt = {
        "render_contract_version": "feedback-language-revision-render-v3",
        "bundle_id": "00000000-0000-0000-0000-000000000001",
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "current_revision_id": "00000000-0000-0000-0000-000000000008",
        "revision_delivery_id": "00000000-0000-0000-0000-000000000005",
        "presentation_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "rendered_exposure_id": "00000000-0000-0000-0000-000000000009",
        "dataset_eligible": False,
    }
    repo.ack_revision_render.return_value = receipt
    monkeypatch.setattr(route, "_repo", lambda: repo)
    body = {
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "revision_delivery_id": "00000000-0000-0000-0000-000000000005",
        "presentation_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "idempotency_key": "render-1",
    }
    with _app().test_request_context("/v2/x", method="POST", json=body):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        response = _raw(route.ack_coach_update_render)(
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000008",
        )
    assert response.get_json() == receipt
    assert repo.ack_revision_render.call_args.kwargs == {
        "recipient_principal_id": "00000000-0000-0000-0000-000000000003",
        "bundle_id": "00000000-0000-0000-0000-000000000001",
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "revision_id": "00000000-0000-0000-0000-000000000008",
        "revision_delivery_id": "00000000-0000-0000-0000-000000000005",
        "presentation_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "idempotency_key": "render-1",
    }


def test_item_render_requires_complete_exact_receipt(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    repo.ack_item_render.return_value = {
        "render_contract_version": "confident-moment-bundle-item-render-v3",
        "bundle_id": "00000000-0000-0000-0000-000000000001",
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "feedback_exposure_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "render_receipt_id": "00000000-0000-0000-0000-000000000010",
        "dataset_eligible": False,
    }
    monkeypatch.setattr(route, "_repo", lambda: repo)
    body = {
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "feedback_exposure_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "idempotency_key": "render-1",
    }
    with _app().test_request_context("/v2/x", method="POST", json=body):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        response = _raw(route.ack_confident_moment_bundle_render)(
            "00000000-0000-0000-0000-000000000001"
        )
    assert response.get_json() == repo.ack_item_render.return_value
    assert repo.ack_item_render.call_args.kwargs["bundle_id"] == (
        "00000000-0000-0000-0000-000000000001"
    )

    repo.ack_item_render.return_value = {"dataset_eligible": False}
    with _app().test_request_context("/v2/x", method="POST", json=body):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        response, status = _raw(route.ack_confident_moment_bundle_render)(
            "00000000-0000-0000-0000-000000000001"
        )
    assert status == 400
    assert response.get_json()["code"] == "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED"


def test_idempotency_key_requires_real_string():
    import routes.v2.confident_moment_bundles as route

    for value in (1, True, ["key"], {"key": "value"}, None):
        with pytest.raises(TypeError):
            route._text(value, "idempotency_key")


def test_uuid_requires_canonical_string_without_object_coercion():
    import routes.v2.confident_moment_bundles as route

    canonical = "abcdefab-cdef-abcd-efab-cdefabcdefab"
    assert route._uuid(canonical, "id") == canonical
    for value in (
        1,
        True,
        [canonical],
        {"id": canonical},
        None,
        canonical.upper(),
        "{00000000-0000-0000-0000-000000000001}",
    ):
        with pytest.raises((TypeError, ValueError)):
            route._uuid(value, "id")


@pytest.mark.parametrize(
    "route_name,extra",
    [
        ("item", {"bundle_id": "00000000-0000-0000-0000-000000000001"}),
        ("coach", {"revision_id": "00000000-0000-0000-0000-000000000008"}),
    ],
)
def test_render_request_rejects_extra_path_identity_before_repository(
    monkeypatch, route_name, extra
):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    monkeypatch.setattr(route, "_repo", lambda: repo)
    body = {
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "idempotency_key": "render-1",
        **extra,
    }
    if route_name == "coach":
        body["presentation_id"] = "00000000-0000-0000-0000-000000000006"
        body["revision_delivery_id"] = "00000000-0000-0000-0000-000000000005"
    else:
        body["feedback_exposure_id"] = "00000000-0000-0000-0000-000000000006"
    with _app().test_request_context("/v2/x", method="POST", json=body):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        if route_name == "item":
            response, status = _raw(route.ack_confident_moment_bundle_render)(
                "00000000-0000-0000-0000-000000000001"
            )
        else:
            response, status = _raw(route.ack_coach_update_render)(
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000008",
            )
    assert status == 400
    assert response.get_json()["code"] == "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED"
    repo.ack_item_render.assert_not_called()
    repo.ack_revision_render.assert_not_called()


def test_render_request_rejects_missing_key_before_repository(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    monkeypatch.setattr(route, "_repo", lambda: repo)
    body = {
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "feedback_exposure_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
    }
    with _app().test_request_context("/v2/x", method="POST", json=body):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        response, status = _raw(route.ack_confident_moment_bundle_render)(
            "00000000-0000-0000-0000-000000000001"
        )
    assert status == 400
    assert response.get_json()["code"] == "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED"
    repo.ack_item_render.assert_not_called()


def test_item_render_rejects_retired_presentation_alias(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    monkeypatch.setattr(route, "_repo", lambda: repo)
    body = {
        "bundle_attachment_id": "00000000-0000-0000-0000-000000000004",
        "presentation_id": "00000000-0000-0000-0000-000000000006",
        "render_instance_id": "00000000-0000-0000-0000-000000000007",
        "idempotency_key": "render-1",
    }
    with _app().test_request_context("/v2/x", method="POST", json=body):
        request.mlc3_principal_id = "00000000-0000-0000-0000-000000000003"
        response, status = _raw(route.ack_confident_moment_bundle_render)(
            "00000000-0000-0000-0000-000000000001"
        )
    assert status == 400
    assert response.get_json()["code"] == "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED"
    repo.ack_item_render.assert_not_called()


def test_only_projection_retry_maps_to_409():
    import routes.v2.confident_moment_bundles as route

    with _app().app_context():
        retry, retry_status = route._database_error(
            RuntimeError("CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED")
        )
        stale, stale_status = route._database_error(
            RuntimeError("CONFIDENT_MOMENT_STALE_REVISION")
        )
    assert retry_status == 409
    assert retry.get_json()["code"] == "CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED"
    assert stale_status != 409
    assert stale.get_json()["code"] == "CONFIDENT_MOMENT_STALE_REVISION"


def test_registration_and_core_summary_use_exact_database_boundary():
    registration = Path("routes/v2_routes.py").read_text()
    core = Path("routes/v2/explore_ideal_text.py").read_text()
    assert "list_confident_moment_bundles" in registration
    assert "ack_confident_moment_bundle_render" in registration
    assert "ack_coach_update_render" in registration
    assert "record_confident_moment_family_response" in registration
    assert "record_confident_moment_root_action" in registration
    assert "update_confident_moment_bundle_text" in registration
    assert "publish_confident_moment_coach_feedback_language" in registration
    handler = core[core.index("def v2_explore_get_ideal_text_core"):]
    handler = handler[:handler.index("\n\n@v2_bp.route", 10)]
    assert "get_ideal_text_document_core_v2" in handler
    assert "load_confident_moment_projection" not in handler
    assert "get_owner_principal_for_user" not in handler
    assert '"items": []' not in handler
    assert "document_snapshot_id" in handler
