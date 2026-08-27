"""Pure Slice 6 founder-canary readiness evaluation.

No product route imports this module.  It consumes aggregate monitoring data
and configuration metadata only—never recordings, transcripts or blind packets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from services.mlc2_confidence_cutover import DARK, resolve_confidence_cutover


READINESS_CONTRACT_VERSION = "mlc2-confidence-canary-readiness-v1"
APPROVED_FOUNDER_EMAIL = "artur@willonski.com"


@dataclass(frozen=True)
class ConfidenceCanaryReadinessReport:
    ready: bool
    blocker_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "readiness_contract_version": READINESS_CONTRACT_VERSION,
            "ready": self.ready,
            "blocker_codes": list(self.blocker_codes),
            "warning_codes": list(self.warning_codes),
            "evidence": self.evidence,
        }


def _count(health: Mapping[str, Any], key: str) -> int:
    value = health.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _valid_uuid(value: Any) -> bool:
    try:
        return bool(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return False


def assess_confidence_canary_readiness(
    health: Mapping[str, Any],
    *,
    cutover_mode: Any,
    configured_founder_email: Any,
    founder_principal_id: Any,
    data_foundation_canary_enabled: bool,
    monitoring_enabled: bool,
    alert_sink_configured: bool,
    dataset_creation_enabled: bool,
    training_enabled: bool,
    promotion_enabled: bool,
) -> ConfidenceCanaryReadinessReport:
    """Fail closed unless every pre-activation gate has explicit evidence."""
    blockers: list[str] = []
    warnings: list[str] = []
    cutover = resolve_confidence_cutover(cutover_mode)
    founder_email = str(configured_founder_email or "").strip().lower()
    principal_valid = _valid_uuid(founder_principal_id)

    if not cutover.valid_configuration:
        blockers.append("invalid_cutover_mode")
    elif cutover.mode != DARK:
        blockers.append("canary_must_remain_dark_during_readiness")
    if founder_email != APPROVED_FOUNDER_EMAIL:
        blockers.append("founder_email_scope_mismatch")
    if not principal_valid:
        blockers.append("founder_principal_not_configured")
    if not data_foundation_canary_enabled:
        blockers.append("founder_attempt_scope_disabled")
    if not monitoring_enabled:
        blockers.append("production_monitor_not_enabled")
    if not alert_sink_configured:
        blockers.append("production_alert_sink_not_configured")

    if health.get("readiness_contract_version") != READINESS_CONTRACT_VERSION:
        blockers.append("readiness_health_contract_mismatch")
    if _count(health, "active_consent_policy_count") != 1:
        blockers.append("active_consent_policy_count_invalid")
    if _count(health, "valid_active_consent_policy_count") != 1:
        blockers.append("product_legal_consent_configuration_invalid")
    if _count(health, "founder_active_bundled_consent_grant_count") < 1:
        blockers.append("founder_bundled_consent_missing")
    if health.get("founder_principal_configured") is not True:
        blockers.append("health_check_missing_founder_principal")

    zero_invariants = (
        "nonfounder_producer_receipt_count",
        "nonfounder_canonical_event_count",
        "pending_confidence_outbox_count",
        "failed_confidence_outbox_count",
        "receipt_without_outbox_count",
        "processed_without_frame_count",
        "blind_assignment_without_packet_count",
        "revealed_without_judgment_count",
    )
    for key in zero_invariants:
        if _count(health, key) != 0:
            blockers.append(f"{key}_nonzero")

    # While this review keeps the producer dark, any receipt is evidence that
    # production state changed without authorization.
    if _count(health, "founder_producer_receipt_count") != 0:
        blockers.append("unexpected_founder_receipts_while_dark")
    if health.get("oldest_pending_confidence_outbox_at") is not None:
        blockers.append("unexpected_pending_outbox_timestamp")

    downstream = {
        "dataset_creation": bool(dataset_creation_enabled)
        or health.get("dataset_creation_enabled") is not False,
        "training": bool(training_enabled)
        or health.get("training_enabled") is not False,
        "promotion": bool(promotion_enabled)
        or health.get("promotion_enabled") is not False,
    }
    for capability, enabled in downstream.items():
        if enabled:
            blockers.append(f"{capability}_must_remain_disabled")

    if _count(health, "founder_producer_receipt_count") == 0:
        warnings.append("no_runtime_canary_receipt_expected_while_dark")

    evidence = {
        "cutover_mode": cutover.mode,
        "canonical_writes_enabled": cutover.canonical_writes_enabled,
        "prior_learning_writes_enabled": cutover.prior_learning_writes_enabled,
        "founder_email_exact": founder_email == APPROVED_FOUNDER_EMAIL,
        "founder_principal_configured": principal_valid,
        "data_foundation_canary_enabled": bool(
            data_foundation_canary_enabled
        ),
        "monitoring_enabled": bool(monitoring_enabled),
        "alert_sink_configured": bool(alert_sink_configured),
        "active_consent_policy_count": _count(
            health, "active_consent_policy_count"
        ),
        "valid_active_consent_policy_count": _count(
            health, "valid_active_consent_policy_count"
        ),
        "founder_active_bundled_consent_grant_count": _count(
            health, "founder_active_bundled_consent_grant_count"
        ),
        "downstream_capabilities_disabled": not any(downstream.values()),
        "aggregate_health_only": True,
    }
    return ConfidenceCanaryReadinessReport(
        ready=not blockers,
        blocker_codes=tuple(dict.fromkeys(blockers)),
        warning_codes=tuple(dict.fromkeys(warnings)),
        evidence=evidence,
    )
