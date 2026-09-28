"""Aggregate-only operational checks for the MLC-3 D4 rollout."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Mapping


MONITOR_CONTRACT_VERSION = "mlc3-general-service-monitor-v1"
_ACTIVE_STATES = {"explicit_cohort", "generally_available"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_MICROSECOND_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
    r"[0-9]{2}\.[0-9]{6}Z$"
)


@dataclass(frozen=True)
class GeneralServiceMonitorReport:
    healthy: bool
    hard_stop: bool
    signal_codes: tuple[str, ...]
    aggregate_health: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "monitor_contract_version": MONITOR_CONTRACT_VERSION,
            "healthy": self.healthy,
            "hard_stop": self.hard_stop,
            "signal_codes": list(self.signal_codes),
            "aggregate_health": self.aggregate_health,
        }


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _too_old(value: object, *, minutes: int, now: datetime) -> bool:
    if value is None:
        return False
    if not isinstance(value, datetime):
        return True
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    observed = value if value.tzinfo else value.replace(tzinfo=UTC)
    return (current - observed).total_seconds() > minutes * 60


#: One raised signal: its code, and whether it is a hard stop.
_Signal = tuple[str, bool]

_CAPACITY_CHECKS = (
    ("active_uploads", "max_concurrent_uploads", "upload_capacity_reached"),
    (
        "maximum_active_uploads_per_principal",
        "max_uploads_per_principal",
        "principal_upload_capacity_reached",
    ),
    (
        "outstanding_required_coach_assignments",
        "max_outstanding_assignments",
        "coach_queue_capacity_reached",
    ),
    (
        "maximum_outstanding_assignments_per_coach",
        "max_assignments_per_coach",
        "coach_capacity_reached",
    ),
    (
        "media_bytes_last_24_hours",
        "max_media_bytes_per_day",
        "media_budget_reached",
    ),
)


def _identity_signals(health: Mapping[str, Any], expected_rollout_state: str,
                      gate_values: tuple[bool, ...]) -> list[_Signal]:
    """The monitor contract, the rollout state, and the four deployment gates
    all agreeing with what this deployment should be doing."""
    found: list[_Signal] = []
    if health.get("monitor_contract_version") != MONITOR_CONTRACT_VERSION:
        found.append(("monitor_contract_mismatch", True))
    if health.get("rollout_state") != expected_rollout_state:
        found.append(("rollout_state_mismatch", True))
    should_serve = expected_rollout_state in _ACTIVE_STATES
    if any(value is not should_serve for value in gate_values):
        found.append(("deployment_gate_mismatch", True))
    for key, signal in (
        ("active_service_rows_without_enrollment", "enrollment_lineage_violation"),
        ("dataset_eligible_rows", "dataset_boundary_violation"),
    ):
        value = _integer(health.get(key))
        if value is None or value != 0:
            found.append((signal, True))
    return found


def _capacity_signals(health: Mapping[str, Any],
                      policy: Mapping[str, Any]) -> list[_Signal]:
    """Each capacity counter against its limit; an unreadable pair is a hard
    stop, an exceeded limit is a soft one."""
    found: list[_Signal] = []
    for observed_key, limit_key, signal in _CAPACITY_CHECKS:
        observed = _integer(health.get(observed_key))
        limit = _integer(policy.get(limit_key))
        if observed is None or limit is None:
            found.append(("capacity_counter_invalid", True))
        elif observed > limit:
            found.append((signal, False))
    return found


def _recovery_signals(health: Mapping[str, Any], policy: Mapping[str, Any],
                      checked_at: datetime) -> list[_Signal]:
    """The unresolved-recovery backlog and its oldest entry."""
    unresolved_practice = _integer(health.get("unresolved_practice_recoveries"))
    unresolved_coach = _integer(health.get("unresolved_coach_recoveries"))
    recovery_limit = _integer(policy.get("max_unresolved_recoveries"))
    recovery_age = _integer(policy.get("max_recovery_age_minutes"))
    if (unresolved_practice is None or unresolved_coach is None
            or recovery_limit is None or recovery_age is None):
        return [("recovery_counter_invalid", True)]
    found: list[_Signal] = []
    if unresolved_practice + unresolved_coach > recovery_limit:
        found.append(("recovery_backlog_blocked", True))
    if _too_old(
        health.get("oldest_unresolved_recovery_at"),
        minutes=recovery_age,
        now=checked_at,
    ):
        found.append(("stale_recovery_blocked", True))
    return found


def _queue_signals(health: Mapping[str, Any], policy: Mapping[str, Any],
                   checked_at: datetime) -> list[_Signal]:
    """The coach queue's age, and the service's lifecycle failures."""
    found: list[_Signal] = []
    queue_age_hours = _integer(policy.get("max_queue_age_hours"))
    if queue_age_hours is None:
        found.append(("coach_queue_policy_invalid", True))
    elif _too_old(
        health.get("oldest_required_coach_assignment_at"),
        minutes=queue_age_hours * 60,
        now=checked_at,
    ):
        found.append(("coach_queue_backpressure", False))
    failure_count = _integer(health.get("service_failure_count"))
    if failure_count is None or failure_count != 0:
        found.append(("service_lifecycle_failure", False))
    return found


def _scanner_invalid(scanner: Mapping[str, Any]) -> bool:
    """The delivery scanner's aggregate does not describe itself
    consistently: counts, hard stop, set hash and oldest start agree."""
    unfinished = _integer(scanner.get("unfinished_over_5s_count"))
    contention = _integer(scanner.get("skipped_contention_60s_count"))
    set_hash = scanner.get("unfinished_set_sha256")
    oldest = scanner.get("oldest_started_at")
    scanner_hard = scanner.get("hard_stop")
    return bool(
        unfinished is None or unfinished < 0
        or contention is None or contention < 0
        or not isinstance(scanner_hard, bool)
        or scanner_hard is not bool(unfinished)
        or (unfinished == 0 and (set_hash is not None or oldest is not None))
        or (unfinished and (
            not isinstance(set_hash, str) or not _SHA256_RE.fullmatch(set_hash)
            or not isinstance(oldest, str)
            or not _UTC_MICROSECOND_RE.fullmatch(oldest)
        ))
    )


def _scanner_signals(scanner: Any) -> list[_Signal]:
    """The confident-moment delivery scanner: invalid, contended, stalled."""
    if not isinstance(scanner, Mapping) or _scanner_invalid(scanner):
        return [("confident_moment_delivery_scanner_invalid", True)]
    found: list[_Signal] = []
    if _integer(scanner.get("skipped_contention_60s_count")):
        found.append(("confident_moment_delivery_contention", False))
    if scanner.get("hard_stop"):
        found.append(("confident_moment_delivery_scanner_stalled", True))
    return found


def assess_general_service_monitor(
    health: Mapping[str, Any],
    *,
    expected_rollout_state: str,
    backend_user_gate: bool,
    backend_coach_gate: bool,
    frontend_user_gate: bool,
    frontend_coach_gate: bool,
    now: datetime | None = None,
) -> GeneralServiceMonitorReport:
    """Map aggregate database state to typed reliability signals only."""
    if expected_rollout_state not in {
        "disabled", "explicit_cohort", "generally_available", "halted",
    }:
        raise ValueError("unsupported expected rollout state")
    checked_at = now or datetime.now(UTC)
    found = _identity_signals(health, expected_rollout_state, (
        backend_user_gate,
        backend_coach_gate,
        frontend_user_gate,
        frontend_coach_gate,
    ))
    policy = health.get("capacity_policy")
    if not isinstance(policy, Mapping):
        found.append(("capacity_policy_missing", True))
        policy = {}
    found += _capacity_signals(health, policy)
    found += _recovery_signals(health, policy, checked_at)
    found += _queue_signals(health, policy, checked_at)
    found += _scanner_signals(health.get("confident_moment_delivery_scanner"))

    deduplicated = tuple(dict.fromkeys(code for code, _ in found))
    return GeneralServiceMonitorReport(
        healthy=not deduplicated,
        hard_stop=any(hard for _, hard in found),
        signal_codes=deduplicated,
        aggregate_health=dict(health),
    )
