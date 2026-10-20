"""
STORY    As a speaker, I want due coach updates swept and queued for delivery
         without exposing the worker's identity, so that my coach's words
         reach me on time.
OUTCOME
  O1  Each due job the scan returns is enqueued exactly once, by its own id.
  O2  The database only ever sees the hashed worker id, never the raw one.
PROVES   O1 -> test_each_due_job_is_queued_once_and_only_the_hashed_worker_id_leaves
         O2 -> test_each_due_job_is_queued_once_and_only_the_hashed_worker_id_leaves
"""
from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import MagicMock

RAW_WORKER_ID = "00000000-0000-0000-0000-000000000001"
JOB_A = "00000000-0000-0000-0000-000000000002"
JOB_B = "00000000-0000-0000-0000-000000000003"
WORKER_HASH = "a" * 64


class _DueJobsDatabase:
    """Answers the sweep's RPCs with valid shapes; two jobs are due."""

    calls: list[tuple[str, dict]] = []

    def __init__(self, _deadline):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def call(self, name, params):
        self.calls.append((name, params))
        run_id = params["p_run_id"]
        if name.startswith("begin_"):
            return {
                "scan_run_contract_version": "feedback-language-delivery-scan-run-v1",
                "run_id": run_id, "started_at": "x", "dataset_eligible": False,
            }
        if name.startswith("mark_"):
            return {"run_id": run_id, "scanner_started_at": "x",
                    "dataset_eligible": False}
        return {
            "delivery_job_claim_contract_version": "feedback-language-delivery-claim-v1",
            "jobs": [{"job_id": JOB_A}, {"job_id": JOB_B}], "has_more": False,
            "frozen_window_count": 2, "acquired_count": 2,
            "contention_nowait_count": 0, "currentness_miss_count": 0,
            "item_results": [{"result": "claimed"}, {"result": "claimed"}],
            "dataset_eligible": False,
        }


def test_each_due_job_is_queued_once_and_only_the_hashed_worker_id_leaves(monkeypatch):
    import services.confident_moment_delivery_worker as worker

    monkeypatch.setattr(worker.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True)
    monkeypatch.setattr(
        worker, "monotonic_deadline_scope", lambda *_a, **_k: nullcontext(),
    )
    monkeypatch.setattr(
        worker, "_worker_process_identity_v1", lambda: (RAW_WORKER_ID, WORKER_HASH)
    )
    _DueJobsDatabase.calls = []
    monkeypatch.setattr(worker, "_BoundedRPCTransport", _DueJobsDatabase)
    enqueue = MagicMock(return_value=True)
    monkeypatch.setattr(worker.job_queue, "enqueue_with_monotonic_deadline", enqueue)

    assert worker.sweep_due_confident_moment_deliveries() is not None

    queued = [call.args for call in enqueue.call_args_list]
    assert queued == [(worker.TASK_PATH, JOB_A), (worker.TASK_PATH, JOB_B)]

    calls = _DueJobsDatabase.calls
    assert calls, "the sweep must reach the database"
    assert all(params["p_worker_id_sha256"] == WORKER_HASH for _n, params in calls)
    assert RAW_WORKER_ID not in repr(calls)
