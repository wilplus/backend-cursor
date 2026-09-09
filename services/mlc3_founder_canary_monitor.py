"""Aggregate-only operational monitor for the MLC-3 founder canary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


MONITOR_CONTRACT_VERSION = "mlc3-founder-canary-monitor-v1"
REQUIRED_SIGNAL_CODES = (
    "service_contract_or_allowlist_violation",
    "authorization_or_deletion_violation",
    "feedback_offer_or_practice_failure",
    "blind_review_or_reveal_failure",
    "coach_guidance_or_inline_authoring_failure",
    "unresolved_practice_media_write",
    "unresolved_coach_media_write",
)


@dataclass(frozen=True)
class FounderCanaryMonitorReport:
    healthy: bool
    signal_codes: tuple[str, ...]
    aggregate_health: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "monitor_contract_version": MONITOR_CONTRACT_VERSION,
            "healthy": self.healthy,
            "signal_codes": list(self.signal_codes),
            "aggregate_health": self.aggregate_health,
        }


def assess_founder_canary_monitor(
    health: Mapping[str, Any], *, expected_contract_state: str,
) -> FounderCanaryMonitorReport:
    """Map only aggregate integrity counts to stable operational signals."""
    if expected_contract_state not in {"disabled", "active"}:
        raise ValueError("expected contract state must be disabled or active")
    signals: list[str] = []
    expected_allowlist = 1 if expected_contract_state == "active" else 0
    if (
        health.get("contract_state") != expected_contract_state
        or health.get("exact_active_allowlist_count") != expected_allowlist
        or health.get("foreign_active_allowlist_count") != 0
    ):
        signals.append("service_contract_or_allowlist_violation")
    count_signals = {
        "authorization_or_deletion_violation_count":
            "authorization_or_deletion_violation",
        "feedback_offer_or_practice_failure_count":
            "feedback_offer_or_practice_failure",
        "blind_review_or_reveal_failure_count":
            "blind_review_or_reveal_failure",
        "coach_guidance_or_inline_authoring_failure_count":
            "coach_guidance_or_inline_authoring_failure",
        "unresolved_practice_media_write_count":
            "unresolved_practice_media_write",
        "unresolved_coach_media_write_count":
            "unresolved_coach_media_write",
    }
    for key, signal in count_signals.items():
        value = health.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            signals.append(signal)
    return FounderCanaryMonitorReport(
        healthy=not signals,
        signal_codes=tuple(dict.fromkeys(signals)),
        aggregate_health=dict(health),
    )
