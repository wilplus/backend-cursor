"""Application transport regressions for accepted D14-D25 boundaries."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask, request

from config import Config
from services.confident_moment_bundle import (
    ConfidentMomentProjectionInvalid,
    validate_bundle_text_update,
    validate_coach_authoring_context,
    validate_family_response,
    validate_owner_edit_transport,
    validate_root_action_result,
)
from services.confident_moment_bundle_repository import (
    ConfidentMomentBundleDisabled,
    ConfidentMomentBundleRepository,
)

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"
U3 = "00000000-0000-0000-0000-000000000003"
U4 = "00000000-0000-0000-0000-000000000004"
U5 = "00000000-0000-0000-0000-000000000005"
H = "a" * 64


def _app() -> Flask:
    app = Flask(__name__)
    app.testing = True
    return app


def _raw(function):
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    return function


def _rpc_client(response: dict):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=response)
    return client


def test_all_bundle_rooting_and_pam_gates_default_disabled():
    assert Config.CONFIDENT_MOMENT_BUNDLE_V1_ENABLED is False
    assert Config.ROOTING_COVERAGE_V1_ENABLED is False
    assert Config.PAM_PROFILE_V1_ENABLED is False
    assert Config.PAM_BASELINE_V1_ENABLED is False
    assert Config.PAM_MATCHING_V1_ENABLED is False
    assert Config.PAM_COACH_AUTHORING_V1_ENABLED is False
    assert Config.PAM_USER_SERVING_V1_ENABLED is False


def test_update_text_repository_uses_d23_database_derived_shape(monkeypatch):
    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    client = _rpc_client({"result": "opaque"})
    repo = ConfidentMomentBundleRepository(lambda: client)
    assert repo.update_text(
        owner_user_id=U1, bundle_id=U2, attachment_id=U3,
        correction_decision_id=U4, feedback_exposure_id=U5,
        render_receipt_id=U1, source_document_snapshot_id=U2,
        source_document_version=3, expected_current_part_revision_id=None,
        expected_user_text_revision=None, expected_user_text_sha256=None,
        expected_part_inventory=[], idempotency_key="update-1",
    ) == {"result": "opaque"}
    name, payload = client.rpc.call_args.args
    assert name == "apply_confident_moment_bundle_text_update_v1"
    assert "p_target_part_id" not in payload
    assert "p_accepted_replacement_text" not in payload
    assert payload["p_expected_part_inventory"] == []


def test_root_repository_requires_both_bundle_and_coverage_gates(monkeypatch):
    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False)
    monkeypatch.setattr(Config, "ROOTING_COVERAGE_V1_ENABLED", True)
    client = _rpc_client({})
    repo = ConfidentMomentBundleRepository(lambda: client)
    with pytest.raises(ConfidentMomentBundleDisabled) as caught:
        repo.freeze_coverage_frame(
            acquisition_principal_id=U1, project_id=U2, take_id=U3,
            feedback_membership_id=U4, document_snapshot_id=U5,
            policy_version="rooting-coverage-30-80-100-v1",
            idempotency_key="coverage-1",
        )
    assert getattr(caught.value, "code", None) == (
        "CONFIDENT_MOMENT_BUNDLE_DISABLED"
    )
    client.rpc.assert_not_called()


def test_update_route_rejects_browser_wording_and_numeric_bigints(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    monkeypatch.setattr(route, "_repo", lambda: repo)
    base = {
        "correction_decision_id": U1,
        "feedback_exposure_id": U2,
        "render_receipt_id": U3,
        "source_document_snapshot_id": U4,
        "source_document_version": 1,
        "expected_current_part_revision_id": None,
        "expected_user_text_revision": None,
        "expected_user_text_sha256": None,
        "expected_part_inventory": [],
        "idempotency_key": "update-1",
    }
    for patch in ({"replacement_text": "spoof"}, {
        "expected_current_part_revision_id": 9007199254740993,
    }):
        with _app().test_request_context("/", method="POST", json={**base, **patch}):
            request.user_id = U5
            request.mlc3_principal_id = U1
            response, status = _raw(route.update_confident_moment_bundle_text)(U2, U3)
        assert status == 400
    repo.update_text.assert_not_called()


def test_family_response_shape_is_closed_and_family_specific():
    row = {
        "family_response_contract_version": "confident-moment-family-response-v1",
        "bundle_id": U1, "bundle_attachment_id": U2,
        "feedback_family": "rewrite_clarity", "response": "apply_suggestion",
        "decision_id": U3, "owner_response_id": None,
        "response_binding_id": None, "dataset_eligible": False,
    }
    assert validate_family_response(row, bundle_id=U1, attachment_id=U2) is row
    row["owner_response_id"] = U4
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_family_response(row, bundle_id=U1, attachment_id=U2)


def test_root_and_text_update_bigints_are_strings_only():
    root = {
        "root_action_contract_version": "confident-moment-root-action-v1",
        "bundle_id": U1, "bundle_attachment_id": U2,
        "product_action_id": U3, "active_root_action_id": U3,
        "interaction_state_revision": "9007199254740993", "is_orange": True,
        "is_locked": False, "can_restore_previous": False,
        "restore_product_action_id": None, "dataset_eligible": False,
    }
    assert validate_root_action_result(root, bundle_id=U1, attachment_id=U2) is root
    root["interaction_state_revision"] = 9007199254740993
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_root_action_result(root, bundle_id=U1, attachment_id=U2)

    update = {
        "bundle_text_update_contract_version": "bundle-text-update-v1",
        "binding_id": U1, "source_document_snapshot_id": U2,
        "source_document_version": 1, "previous_user_text_revision": None,
        "result_user_text_revision": "1", "previous_user_text_sha256": None,
        "result_user_text_sha256": H, "target_part_id": U3,
        "result_part_revision_id": "9007199254740993",
        "dataset_eligible": False,
    }
    assert validate_bundle_text_update(update) is update


def test_owner_edit_read_is_recursively_closed_and_null_head_is_real_state():
    owner = {
        "text": "A", "source_document_version": 1,
        "user_text_revision": "9007199254740993", "user_text_sha256": H,
        "parts": [{"id": U1, "ord": 0, "text": "A", "locked": False,
                   "current_part_revision_id": None}],
        "current_bundle_text_update_binding": None,
    }
    assert validate_owner_edit_transport(owner) is owner
    owner["parts"][0]["revision"] = None
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_owner_edit_transport(owner)


def test_owner_lane_has_one_rpc_writer_and_no_route_post_rpc_part_write():
    db_source = Path("services/db.py").read_text()
    route_source = Path("routes/v2/explore_ideal_text.py").read_text()
    tree = ast.parse(db_source)
    calls = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "rpc"
        and call.args and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "compare_and_set_user_ideal_edit_v1"
    ]
    assert calls == ["compare_and_set_user_ideal_edit_v1"]
    owner_route = route_source[route_source.index(
        "def v2_explore_put_ideal_user_edit"
    ):]
    assert "db.upsert_user_ideal_edit(" not in owner_route
    assert "db.replace_ideal_text_parts(" not in owner_route


def test_delivery_worker_is_dark_and_transports_only_job_identity(monkeypatch):
    from services import confident_moment_delivery_worker as worker

    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False)
    monkeypatch.setattr(worker.job_queue, "enqueue", MagicMock())
    assert worker.enqueue_confident_moment_delivery(U1) is False
    worker.job_queue.enqueue.assert_not_called()


def test_delivery_worker_enabled_uses_exact_rpc_and_validates_result(monkeypatch):
    from services import confident_moment_delivery_worker as worker
    from services.db import db

    monkeypatch.setattr(worker.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    result = {
        "job_id": U1, "job_state": "completed", "delivery_id": U2,
        "cause_code": "delivery_materialized",
        "dataset_eligible": False,
    }
    client = _rpc_client(result)
    monkeypatch.setattr(db, "client", client)
    assert worker.materialize_confident_moment_delivery(U1) == result
    client.rpc.assert_called_once_with(
        "materialize_feedback_language_delivery_job_v1",
        {"p_job_id": U1, "p_idempotency_key": f"materialize:{U1}"},
    )


def test_coach_authoring_extension_is_recursively_closed():
    context = {
        "items": [{
            "review_batch_id": U1,
            "bundle_authoring_context": {
                "bundle_id": U2,
                "source_review_attachment_id": U3,
                "authorized_targets": [{
                    "bundle_attachment_id": U4,
                    "review_assignment_id": U1,
                    "reveal_access_id": U2,
                    "feedback_family": "rewrite_clarity",
                    "allowed_output_kind": "rephrase",
                    "allowed_comment_purpose": None,
                    "source_passage": {
                        "evidence_span_id": U5,
                        "text": "Use one clear next step.",
                        "text_sha256": H,
                    },
                    "expected_current_revision_id": None,
                    "expected_current_delivery_id": None,
                }],
            },
        }],
    }
    assert validate_coach_authoring_context(context) is context
    context["items"][0]["bundle_authoring_context"]["authorized_targets"][0][
        "blind_judgment_id"
    ] = U1
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_coach_authoring_context(context)


def test_coach_context_repository_uses_database_derived_principal_v2(monkeypatch):
    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    context = {"items": []}
    client = _rpc_client(context)
    repo = ConfidentMomentBundleRepository(lambda: client)
    assert repo.project_coach_authoring_context(
        project_id=U1, reviewer_principal_id=U2, idempotency_key="context-1"
    ) == context
    client.rpc.assert_called_once_with(
        "project_confident_moment_coach_authoring_context_v2",
        {
            "p_project_id": U1,
            "p_reviewer_principal_id": U2,
            "p_idempotency_key": "context-1",
        },
    )


def test_root_route_rejects_cross_lane_source_mix_before_rpc(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    monkeypatch.setattr(route, "_repo", lambda: repo)
    body = {
        "bundle_attachment_id": U2,
        "action": "save_owner_selected_root",
        "expected_block_head_action_id": None,
        "source_feedback_exposure_id": U3,
        "source_owner_response_id": U4,
        "source_practice_attempt_id": None,
        "source_ideal_text_revision_id": "7",
        "source_text_update_binding_id": U5,
        "source_target_speaker_binding_id": None,
        "practice_target_speaker_binding_id": None,
        "restore_product_action_id": None,
        "policy_version": "rooting-coverage-30-80-100-v1",
        "idempotency_key": "root-1",
    }
    with _app().test_request_context("/", method="POST", json=body):
        request.mlc3_principal_id = U1
        response, status = _raw(route.record_confident_moment_root_action)(U1)
    assert status == 400
    repo.record_root_action.assert_not_called()


def test_d5_context_seam_uses_bundle_wrapper_when_bundle_gate_is_on(monkeypatch):
    import routes.v2.coach_guidance_delivery as route
    import services.confident_moment_bundle_repository as repository_module

    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    monkeypatch.setattr(route, "runtime_is_enabled", lambda: False)
    monkeypatch.setattr(route, "inline_authoring_is_enabled", lambda: False)
    monkeypatch.setattr(route, "_reviewer_principal_id", lambda: U2)
    route.db.get_project_identity = MagicMock()
    route.db.prepare_coach_inline_guidance_context = MagicMock()
    wrapper = MagicMock()
    wrapper.project_coach_authoring_context.return_value = {"items": []}
    monkeypatch.setattr(
        repository_module, "ConfidentMomentBundleRepository",
        lambda client_provider: wrapper,
    )
    with _app().test_request_context("/", method="GET"):
        response, status = _raw(route.v2_coach_guidance_batch)(U3)
    assert status == 200
    assert response.get_json() == {"items": []}
    wrapper.project_coach_authoring_context.assert_called_once_with(
        project_id=U3,
        reviewer_principal_id=U2,
        idempotency_key=f"confident-moment-coach-context:{U3}:{U2}",
    )
    route.db.prepare_coach_inline_guidance_context.assert_not_called()
    route.db.get_project_identity.assert_not_called()
