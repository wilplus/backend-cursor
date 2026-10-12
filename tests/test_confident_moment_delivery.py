"""Focused application regressions for accepted D27-D37 seams."""
from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock

U1 = "00000000-0000-0000-0000-000000000001"
U2 = "00000000-0000-0000-0000-000000000002"
H = "a" * 64


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
