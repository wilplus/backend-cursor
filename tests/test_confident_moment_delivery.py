"""Focused application regressions for accepted D27-D37 seams."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config import Config
from services.confident_moment_bundle import (
    ConfidentMomentProjectionInvalid,
    validate_ideal_text_core_v2,
)
from services.confident_moment_bundle_repository import (
    ConfidentMomentBundleRepository,
    PublishCoachFeedbackLanguageResult,
)

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"
U3 = "00000000-0000-0000-0000-000000000003"
H = "a" * 64


def _core() -> dict:
    return {
        "ideal_text_core_read_contract_version": "ideal-text-document-core-v2",
        "snapshot": {
            "id": U1, "arc_id": "arc", "actor_id": "actor",
            "acquisition_principal_id": U2, "project_id": U2,
            "source_take_session_id": U3, "version": 1,
            "source_generation": "0", "source_fingerprint_sha256": H,
            "payload_sha256": H, "payload": {"text": "hello"},
            "enrichment_seed": {}, "supersedes_id": None,
            "created_at": "2026-09-12T12:34:56.000000Z",
        },
        "dynamic_overlay": {
            "owner_edit": {
                "text": None, "source_document_version": None,
                "user_text_revision": None, "user_text_sha256": None,
                "parts": [], "current_bundle_text_update_binding": None,
            },
            "confident_moment_summary": None,
            "confident_moment_summary_status": {
                "state": "disabled", "code": None, "retryable": False,
            },
        },
        "read_sha256": H,
    }


def test_core_v2_parser_is_exact_and_preserves_zero_bigint_string():
    value = _core()
    assert validate_ideal_text_core_v2(value) is value
    value["snapshot"]["source_generation"] = 0
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_ideal_text_core_v2(value)


@pytest.mark.parametrize("created_at", [
    "2026-09-12T12:34:56Z",
    "2026-09-12T12:34:56.00000Z",
    "2026-09-12T12:34:56.000000+00:00",
])
def test_core_v2_timestamp_is_exact_six_digit_utc(created_at):
    value = _core()
    value["snapshot"]["created_at"] = created_at
    with pytest.raises(ConfidentMomentProjectionInvalid):
        validate_ideal_text_core_v2(value)


def test_publish_repository_strips_internal_job_identity(monkeypatch):
    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    public = {
        "coach_feedback_language_contract_version": (
            "confident-moment-coach-feedback-language-v1"
        ),
        "bundle_id": U1, "bundle_attachment_id": U2,
        "revision_id": U3, "revision_sha256": H,
        "delivery_id": None, "delivery_state": None, "target_take_id": None,
        "dataset_eligible": False,
    }
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(
        data={**public, "_materialization_job_id": U3}
    )
    repo = ConfidentMomentBundleRepository(lambda: client)
    result = repo.publish_coach_feedback_language(
        reviewer_principal_id=U3, bundle_id=U1, bundle_attachment_id=U2,
        review_batch_id=U1, reveal_grant_id=U1, reveal_access_id=U1,
        review_assignment_id=U1, output_kind="comment",
        comment_purpose="positive_praise", revision_text="Good.",
        expected_current_revision_id=None, expected_current_delivery_id=None,
        idempotency_key="publish-1",
    )
    assert result == PublishCoachFeedbackLanguageResult(public, U3)
    assert "_materialization_job_id" not in result.public_payload


def test_worker_identity_is_pid_local_and_only_digest_is_stable(monkeypatch):
    import services.confident_moment_delivery_worker as worker

    monkeypatch.setattr(worker, "_WORKER_IDENTITY", None)
    monkeypatch.setattr(worker.os, "getpid", lambda: 101)
    raw, digest = worker._worker_process_identity_v1()
    assert digest == hashlib.sha256(
        f"confident-moment-worker-v1:{raw}".encode()
    ).hexdigest()
    assert worker._worker_process_identity_v1() == (raw, digest)
    monkeypatch.setattr(worker.os, "getpid", lambda: 102)
    assert worker._worker_process_identity_v1()[0] != raw


def test_sweep_uses_exact_d37_rpc_chain_and_opaque_jobs(monkeypatch):
    import services.confident_moment_delivery_worker as worker

    monkeypatch.setattr(worker.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    monkeypatch.setattr(
        worker, "monotonic_deadline_scope",
        lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        worker, "_worker_process_identity_v1", lambda: (U1, H)
    )
    calls = []

    class Transport:
        def __init__(self, _deadline):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def call(self, name, params):
            calls.append((name, params))
            run_id = params["p_run_id"]
            if name.startswith("begin_"):
                return {
                    "scan_run_contract_version": (
                        "feedback-language-delivery-scan-run-v1"
                    ),
                    "run_id": run_id, "started_at": "x",
                    "dataset_eligible": False,
                }
            if name.startswith("mark_"):
                return {"run_id": run_id, "scanner_started_at": "x",
                        "dataset_eligible": False}
            return {
                "delivery_job_claim_contract_version": (
                    "feedback-language-delivery-claim-v1"
                ),
                "jobs": [{"job_id": U2}], "has_more": False,
                "frozen_window_count": 1, "acquired_count": 1,
                "contention_nowait_count": 0, "currentness_miss_count": 0,
                "item_results": [{"result": "claimed"}],
                "dataset_eligible": False,
            }

    monkeypatch.setattr(worker, "_BoundedRPCTransport", Transport)
    enqueue = MagicMock(return_value=True)
    monkeypatch.setattr(
        worker.job_queue, "enqueue_with_monotonic_deadline", enqueue
    )
    assert worker.sweep_due_confident_moment_deliveries() is not None
    assert [name for name, _params in calls] == [
        "begin_feedback_language_delivery_scan_run_v1",
        "mark_feedback_language_delivery_scan_started_v1",
        "scan_due_feedback_language_delivery_jobs_v1",
    ]
    scan_params = calls[-1][1]
    assert scan_params["p_limit"] == 3
    assert scan_params["p_worker_id_sha256"] == H
    assert U1 not in repr(calls)
    enqueue.assert_called_once()
    assert enqueue.call_args.args == (
        worker.TASK_PATH, U2,
    )


def test_sweep_rejects_invalid_lease_before_transport(monkeypatch):
    import services.confident_moment_delivery_worker as worker

    monkeypatch.setattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    transport = MagicMock()
    monkeypatch.setattr(worker, "_BoundedRPCTransport", transport)
    assert worker.sweep_due_confident_moment_deliveries(lease_seconds=2) is None
    transport.assert_not_called()


@pytest.mark.parametrize("armed_count", [0, 2])
def test_take_arm_passes_exact_promotion_key_and_accepts_set_hash(
    monkeypatch, armed_count,
):
    import services.confident_moment_delivery_worker as worker
    from services.db import db

    monkeypatch.setattr(
        worker.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True
    )
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data={
        "delivery_job_arm_contract_version":
            "feedback-language-delivery-arm-v1",
        "armed_count": armed_count,
        "armed_set_sha256": H,
        "dataset_eligible": False,
    })
    monkeypatch.setattr(db, "client", client)

    assert worker.arm_confident_moment_deliveries_for_take(
        U1, "exact-promotion-key"
    ) is True
    assert client.rpc.call_args.args == (
        "arm_feedback_language_delivery_jobs_for_take_v1",
        {"p_take_id": U1, "p_idempotency_key": "exact-promotion-key"},
    )


@pytest.mark.parametrize(("state", "cause", "delivery"), [
    ("completed", "delivery_materialized", U2),
    ("closed_stale", "revision_superseded", None),
    ("closed_stale", "authority_withdrawn", None),
    ("failed_retryable", "lock_timeout", None),
    ("failed_retryable", "enqueue_lease_expired", None),
])
def test_materializer_accepts_only_closed_six_key_contract(
    monkeypatch, state, cause, delivery,
):
    import services.confident_moment_delivery_worker as worker
    from services.db import db

    monkeypatch.setattr(worker.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    payload = {
        "job_id": U1, "job_state": state, "delivery_id": delivery,
        "cause_code": cause, "dataset_eligible": False,
    }
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=payload)
    monkeypatch.setattr(db, "client", client)
    assert worker.materialize_confident_moment_delivery(U1) == payload
    assert client.rpc.call_args.args == (
        "materialize_feedback_language_delivery_job_v1",
        {"p_job_id": U1, "p_idempotency_key": f"materialize:{U1}"},
    )


@pytest.mark.parametrize("mutation", [
    {"cause_code": "temporary_database_failure", "delivery_id": U2},
    {"job_state": "completed", "cause_code": "authority_withdrawn"},
    {"dataset_eligible": True},
    {"extra": "field"},
])
def test_materializer_rejects_cross_state_or_expanded_response(monkeypatch, mutation):
    import services.confident_moment_delivery_worker as worker
    from services.db import db

    monkeypatch.setattr(worker.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    payload = {
        "job_id": U1, "job_state": "failed_retryable", "delivery_id": None,
        "cause_code": "temporary_database_failure", "dataset_eligible": False,
    }
    payload.update(mutation)
    client = MagicMock()
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=payload)
    monkeypatch.setattr(db, "client", client)
    with pytest.raises(TypeError):
        worker.materialize_confident_moment_delivery(U1)
