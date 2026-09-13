"""Bounded asynchronous Feedback Language delivery materialization.

The durable PostgreSQL job is authoritative. Redis/RQ is only a wake-up
mechanism; enqueue failure never changes the already-committed product result.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
import math
import os
import signal
import threading
import time
import uuid
from typing import Any, Iterator

from config import Config
from services import job_queue

logger = logging.getLogger(__name__)
TASK_PATH = (
    "services.confident_moment_delivery_worker."
    "materialize_confident_moment_delivery"
)
_CONFIDENT_MOMENT_BOOT_SWEEP_TOKEN = object()
_WORKER_IDENTITY: tuple[int, str, str] | None = None


class ConfidentMomentSweepDeadline(BaseException):
    """Private whole-sweep cancellation sentinel."""


class PriorAlarmReturned(BaseException):
    """A preserved earlier SIGALRM handler unexpectedly returned."""


class UnsupportedDeadlineContext(RuntimeError):
    """The hard deadline cannot safely be owned in this process context."""


def _job_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        canonical = str(uuid.UUID(value))
    except ValueError:
        return None
    return canonical if canonical == value else None


def _sha256(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return value if value == value.lower() else None


def _worker_process_identity_v1() -> tuple[str, str]:
    """Return one PID-local UUIDv4 and its non-secret namespaced digest."""
    global _WORKER_IDENTITY
    pid = os.getpid()
    if _WORKER_IDENTITY is None or _WORKER_IDENTITY[0] != pid:
        raw = str(uuid.uuid4())
        digest = hashlib.sha256(
            f"confident-moment-worker-v1:{raw}".encode()
        ).hexdigest()
        _WORKER_IDENTITY = (pid, raw, digest)
    return _WORKER_IDENTITY[1], _WORKER_IDENTITY[2]


def _registered_deadline_context(boot_token: object | None) -> bool:
    try:
        from rq import get_current_job
        current = get_current_job()
    except Exception:  # noqa: BLE001 - local RQ state only
        current = None
    if boot_token is _CONFIDENT_MOMENT_BOOT_SWEEP_TOKEN:
        return current is None
    return current is not None and getattr(current, "func_name", None) == (
        "services.pipeline_jobs.run_sweep_loop"
    )


def _dispatch_prior_alarm(handler: object, signum: int, frame: object) -> None:
    if handler is signal.SIG_DFL:
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGALRM)
        raise PriorAlarmReturned()
    if not callable(handler):
        raise UnsupportedDeadlineContext("prior SIGALRM handler is not callable")
    handler(signum, frame)
    raise PriorAlarmReturned()


@contextmanager
def monotonic_deadline_scope(
    deadline_monotonic: float,
    *,
    boot_token: object | None = None,
) -> Iterator[None]:
    """Own one alarm without extending or swallowing an earlier one-shot."""
    supported = (
        os.name == "posix"
        and threading.current_thread() is threading.main_thread()
        and all(hasattr(signal, name) for name in (
            "SIGALRM", "ITIMER_REAL", "getitimer", "setitimer",
        ))
        and _registered_deadline_context(boot_token)
    )
    if not supported or not math.isfinite(deadline_monotonic):
        raise UnsupportedDeadlineContext("unsupported deadline context")
    prior_handler = signal.getsignal(signal.SIGALRM)
    prior_remaining, prior_interval = signal.getitimer(signal.ITIMER_REAL)
    snapshot = time.monotonic()
    if (
        not all(math.isfinite(value) and value >= 0 for value in (
            prior_remaining, prior_interval,
        ))
        or prior_interval != 0
        or prior_handler is signal.SIG_IGN
        or (prior_remaining > 0 and not (
            prior_handler is signal.SIG_DFL or callable(prior_handler)
        ))
    ):
        raise UnsupportedDeadlineContext("prior alarm cannot be preserved")
    prior_deadline = snapshot + prior_remaining if prior_remaining > 0 else None
    armed_deadline = min(
        deadline_monotonic,
        prior_deadline if prior_deadline is not None else deadline_monotonic,
    )
    prior_dispatched = False

    def arbitrate(signum: int, frame: object) -> None:
        nonlocal prior_dispatched
        if prior_deadline is not None and prior_deadline <= deadline_monotonic:
            prior_dispatched = True
            _dispatch_prior_alarm(prior_handler, signum, frame)
        raise ConfidentMomentSweepDeadline()

    signal.signal(signal.SIGALRM, arbitrate)
    signal.setitimer(
        signal.ITIMER_REAL,
        max(0.000001, armed_deadline - time.monotonic()),
        0.0,
    )
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0, 0.0)
        signal.signal(signal.SIGALRM, prior_handler)
        if prior_deadline is not None and not prior_dispatched:
            remaining = prior_deadline - time.monotonic()
            if remaining > 0:
                signal.setitimer(signal.ITIMER_REAL, remaining, 0.0)
            else:
                _dispatch_prior_alarm(prior_handler, signal.SIGALRM, None)


class _BoundedRPCTransport:
    """One isolated Supabase transport for one bounded sweep turn."""

    def __init__(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConfidentMomentSweepDeadline()
        from supabase import create_client
        from supabase.lib.client_options import ClientOptions

        supabase_url = Config.SUPABASE_URL
        service_role_key = Config.SUPABASE_SERVICE_ROLE_KEY
        if not isinstance(supabase_url, str) or not isinstance(
            service_role_key, str
        ):
            raise RuntimeError("Supabase service configuration is unavailable")
        self._client = create_client(
            supabase_url,
            service_role_key,
            options=ClientOptions(
                auto_refresh_token=False,
                persist_session=False,
                postgrest_client_timeout=max(0.001, remaining),
                function_client_timeout=max(0.001, remaining),
            ),
        )

    def call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        result = self._client.rpc(name, params).execute()
        data = getattr(result, "data", result)
        if type(data) is not dict:
            raise TypeError(f"{name} returned non-object")
        return data

    def __enter__(self) -> "_BoundedRPCTransport":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        postgrest = getattr(self._client, "_postgrest", None)
        if postgrest is not None:
            postgrest.aclose()


def _validate_begin(value: dict[str, Any], run_id: str) -> dict[str, Any]:
    if set(value) != {
        "scan_run_contract_version", "run_id", "started_at", "dataset_eligible",
    } or value.get("scan_run_contract_version") != (
        "feedback-language-delivery-scan-run-v1"
    ) or value.get("run_id") != run_id or not isinstance(
        value.get("started_at"), str
    ) or value.get("dataset_eligible") is not False:
        raise TypeError("scan begin response invalid")
    return value


def _validate_mark(value: dict[str, Any], run_id: str) -> dict[str, Any]:
    if set(value) != {"run_id", "scanner_started_at", "dataset_eligible"} or (
        value.get("run_id") != run_id
        or not isinstance(value.get("scanner_started_at"), str)
        or value.get("dataset_eligible") is not False
    ):
        raise TypeError("scan start response invalid")
    return value


def _validate_abandon(value: dict[str, Any], run_id: str) -> dict[str, Any]:
    if set(value) != {"run_id", "result_code", "dataset_eligible"} or (
        value.get("run_id") != run_id
        or value.get("result_code") != "abandoned_before_scan"
        or value.get("dataset_eligible") is not False
    ):
        raise TypeError("scan abandonment response invalid")
    return value


_SCAN_RESULTS = {
    "contention_nowait", "currentness_miss", "advisory_contention",
    "deferred_no_target", "active_lease", "exhausted", "claimed",
}


def _validate_scan(value: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "delivery_job_claim_contract_version", "jobs", "has_more",
        "frozen_window_count", "acquired_count", "contention_nowait_count",
        "currentness_miss_count", "item_results", "dataset_eligible",
    }
    if set(value) != expected or value.get(
        "delivery_job_claim_contract_version"
    ) != "feedback-language-delivery-claim-v1" or value.get(
        "dataset_eligible"
    ) is not False or not isinstance(value.get("has_more"), bool):
        raise TypeError("delivery scan response invalid")
    jobs = value.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > 3:
        raise TypeError("delivery scan jobs invalid")
    seen: set[str] = set()
    for item in jobs:
        if type(item) is not dict or set(item) != {"job_id"}:
            raise TypeError("delivery scan job shape invalid")
        job_id = _job_id(item.get("job_id"))
        if job_id is None or job_id in seen:
            raise TypeError("delivery scan job identity invalid")
        seen.add(job_id)
    counts = []
    for field in (
        "frozen_window_count", "acquired_count", "contention_nowait_count",
        "currentness_miss_count",
    ):
        number = value.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 3:
            raise TypeError("delivery scan count invalid")
        counts.append(number)
    frozen, acquired, contention, currentness = counts
    if acquired + contention + currentness > frozen:
        raise TypeError("delivery scan counts do not reconcile")
    results = value.get("item_results")
    if not isinstance(results, list) or len(results) != frozen:
        raise TypeError("delivery scan item results invalid")
    for item in results:
        if type(item) is not dict or set(item) != {"result"} or item.get(
            "result"
        ) not in _SCAN_RESULTS:
            raise TypeError("delivery scan item result invalid")
    return value


def enqueue_confident_moment_delivery(job_id: str) -> bool:
    """Best-effort one-job wake-up; never broadens the Bundle gate."""
    if not bool(getattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False)):
        return False
    normalized_job_id = _job_id(job_id)
    if normalized_job_id is None:
        return False
    return job_queue.enqueue(
        TASK_PATH,
        normalized_job_id,
        rq_job_id=f"confident-moment-delivery-{normalized_job_id}",
    )


def arm_confident_moment_deliveries_for_take(
    take_id: str,
    promotion_idempotency_key: str,
) -> bool:
    """Best-effort post-promotion arm; the durable due probe is backstop."""
    if not bool(getattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False)):
        return False
    normalized_take_id = _job_id(take_id)
    if normalized_take_id is None or not isinstance(
        promotion_idempotency_key, str
    ) or not (
        promotion_idempotency_key.strip()
    ):
        return False
    try:
        from services.db import db
        result = db.client.rpc(
            "arm_feedback_language_delivery_jobs_for_take_v1",
            {
                "p_take_id": normalized_take_id,
                "p_idempotency_key": promotion_idempotency_key,
            },
        ).execute()
        data = getattr(result, "data", result)
        if type(data) is not dict or set(data) != {
            "delivery_job_arm_contract_version", "armed_count",
            "armed_set_sha256", "dataset_eligible",
        } or data.get("delivery_job_arm_contract_version") != (
            "feedback-language-delivery-arm-v1"
        ) or data.get("dataset_eligible") is not False:
            raise TypeError("delivery arm response invalid")
        count = data.get("armed_count")
        digest = data.get("armed_set_sha256")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise TypeError("delivery arm count invalid")
        if _sha256(digest) is None:
            raise TypeError("delivery arm set hash invalid")
        return True
    except Exception as error:  # noqa: BLE001 - Take is already committed
        logger.warning("confident-moment Take arm failed: %s", error)
        return False


def sweep_due_confident_moment_deliveries(
    *,
    lease_seconds: int = 60,
    _boot_token: object | None = None,
) -> dict[str, Any] | None:
    """Run one whole-client bounded scan and enqueue at most three jobs."""
    sweep_started = time.monotonic()
    adapter_deadline = sweep_started + 1.900
    hard_return_deadline = sweep_started + 2.000
    if not bool(getattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False)):
        return None
    if not 15 <= lease_seconds <= 300:
        return None
    _raw_worker_id, worker_hash = _worker_process_identity_v1()
    run_id = str(uuid.uuid4())
    try:
        with monotonic_deadline_scope(
            adapter_deadline, boot_token=_boot_token
        ):
            with _BoundedRPCTransport(adapter_deadline) as transport:
                _validate_begin(transport.call(
                "begin_feedback_language_delivery_scan_run_v1",
                {
                    "p_run_id": run_id,
                    "p_worker_id_sha256": worker_hash,
                    "p_idempotency_key": (
                        f"delivery-scan-begin-v1:{run_id}:{worker_hash}"
                    ),
                },
                ), run_id)
                if adapter_deadline - time.monotonic() <= 0.100:
                    _validate_abandon(transport.call(
                        "abandon_feedback_language_delivery_scan_run_v1",
                        {
                            "p_run_id": run_id,
                            "p_worker_id_sha256": worker_hash,
                            "p_idempotency_key": (
                                f"delivery-scan-abandon-v1:{run_id}:{worker_hash}"
                            ),
                        },
                    ), run_id)
                    return None
                _validate_mark(transport.call(
                "mark_feedback_language_delivery_scan_started_v1",
                {
                    "p_run_id": run_id,
                    "p_worker_id_sha256": worker_hash,
                    "p_idempotency_key": (
                        f"delivery-scan-start-v1:{run_id}:{worker_hash}"
                    ),
                },
                ), run_id)
                remaining_ms = math.floor(max(
                    1.0,
                    min(
                        1500.0,
                        (adapter_deadline - time.monotonic()) * 1000.0 - 100.0,
                    ),
                ))
                scan = _validate_scan(transport.call(
                "scan_due_feedback_language_delivery_jobs_v1",
                {
                    "p_run_id": run_id,
                    "p_worker_id_sha256": worker_hash,
                    "p_limit": 3,
                    "p_lease_seconds": lease_seconds,
                    "p_server_budget_ms": remaining_ms,
                },
                ))
                for item in scan["jobs"]:
                    if time.monotonic() >= adapter_deadline:
                        break
                    job_id = item["job_id"]
                    if not job_queue.enqueue_with_monotonic_deadline(
                        TASK_PATH,
                        job_id,
                        rq_job_id=f"confident-moment-delivery-{job_id}",
                        deadline_monotonic=adapter_deadline,
                    ):
                        break
                return scan
    except ConfidentMomentSweepDeadline:
        return None
    except UnsupportedDeadlineContext:
        return None
    except Exception as error:  # noqa: BLE001 - bounded operational turn
        logger.warning("confident-moment delivery scan failed: %s", error)
        return None
    finally:
        if time.monotonic() > hard_return_deadline:
            logger.error("confident-moment delivery sweep exceeded hard deadline")


def materialize_confident_moment_delivery(job_id: str) -> dict[str, Any] | None:
    """Execute one bounded exact materialization attempt.

    PostgreSQL derives the target Take, current revision and authority. The
    worker transports only the durable job identity and a stable attempt key.
    """
    if not bool(getattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False)):
        return None
    normalized_job_id = _job_id(job_id)
    if normalized_job_id is None:
        return None
    from services.db import db

    result = db.client.rpc(
        "materialize_feedback_language_delivery_job_v1",
        {
            "p_job_id": normalized_job_id,
            "p_idempotency_key": f"materialize:{normalized_job_id}",
        },
    ).execute()
    data = getattr(result, "data", result)
    if type(data) is not dict:
        raise TypeError(
            "materialize_feedback_language_delivery_job_v1 returned non-object"
        )
    if set(data) != {
        "job_id", "job_state", "delivery_id", "cause_code",
        "dataset_eligible",
    }:
        raise TypeError("materialization result keys invalid")
    if data.get("job_id") != normalized_job_id or data.get(
        "dataset_eligible"
    ) is not False:
        raise TypeError("materialization result identity invalid")
    state = data.get("job_state")
    causes = {
        "completed": {"delivery_materialized"},
        "closed_stale": {
            "revision_superseded", "authority_withdrawn",
            "source_deleted_or_purged", "attachment_invalidated",
            "recipient_or_project_invalid",
            "delivery_already_resolved_elsewhere",
        },
        "failed_retryable": {
            "lock_timeout", "target_take_changed",
            "temporary_database_failure", "enqueue_lease_expired",
        },
    }
    if state not in causes or data.get("cause_code") not in causes[state]:
        raise TypeError("materialization result state invalid")
    delivery_id = data.get("delivery_id")
    if state == "completed":
        if _job_id(delivery_id) is None:
            raise TypeError("materialization delivery identity invalid")
    elif delivery_id is not None:
        raise TypeError("stale materialization cannot create delivery")
    return data
