"""Pure Slice 6 confidence-canary readiness evaluation, read against rings.

No product route imports this module.  It consumes aggregate monitoring data
and configuration metadata only—never recordings, transcripts or blind packets.

RINGS (0394, founder 2026-09-29). The canary's "who" used to be a founder
email baked into the code and a principal id in a Railway variable. It is
now the ``confidence_learning_writes`` ring row: the people that row reaches
are the eligible principals, and the zero-invariants assert that ONLY
ring-eligible principals wrote canonical rows or producer receipts. The
canonical-Take door in front of it is the ``canonical_take_rows`` row. The
writer state (``MLC2_CONFIDENCE_CUTOVER_MODE``) is not a "who" and stays a
code constant; readiness still requires it dark, and the one-way row's kill
reads as ``killed`` through ``configured_confidence_cutover``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from services.mlc2_confidence_cutover import DARK, resolve_confidence_cutover
from services.mlc3_founder_canary_readiness import _count


READINESS_CONTRACT_VERSION = "mlc2-confidence-canary-readiness-v1"
RING_READINESS_CONTRACT_VERSION = "rings-confidence-readiness-v1"
CONFIDENCE_RING_FEATURE = "confidence_learning_writes"
CANONICAL_ROWS_RING_FEATURE = "canonical_take_rows"


@dataclass(frozen=True)
class ConfidenceCanaryReadinessReport:
    ready: bool
    blocker_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "readiness_contract_version": READINESS_CONTRACT_VERSION,
            "ring_readiness_contract_version": RING_READINESS_CONTRACT_VERSION,
            "ready": self.ready,
            "blocker_codes": list(self.blocker_codes),
            "warning_codes": list(self.warning_codes),
            "evidence": self.evidence,
        }


def _flag(mapping: Mapping[str, Any], key: str) -> bool:
    return mapping.get(key) is True


def _ring_blockers(ring_health: Mapping[str, Any]) -> list[str]:
    """The canary's "who", read from the ring rows (0394)."""
    blockers: list[str] = []
    if ring_health.get("ring_readiness_contract_version") != RING_READINESS_CONTRACT_VERSION:
        blockers.append("ring_readiness_contract_mismatch")
    if not _flag(ring_health, "confidence_ring_row_present"):
        blockers.append("confidence_ring_row_missing")
    elif _flag(ring_health, "confidence_ring_row_killed"):
        blockers.append("confidence_ring_row_killed")
    if not _flag(ring_health, "confidence_ring_row_one_way"):
        blockers.append("confidence_ring_row_not_one_way")
    if not _flag(ring_health, "canonical_take_rows_row_present"):
        blockers.append("canonical_take_rows_row_missing")
    elif _flag(ring_health, "canonical_take_rows_row_killed"):
        blockers.append("canonical_take_rows_row_killed")
    if _count(ring_health, "eligible_principal_count") < 1:
        blockers.append("no_ring_eligible_principal")
    if _count(ring_health, "eligible_bundled_consent_grant_count") < 1:
        blockers.append("eligible_bundled_consent_missing")
    # Only ring-eligible principals may have written anything, and while the
    # producer is dark not even they may have.
    for key in ("noneligible_producer_receipt_count",
                "noneligible_canonical_event_count"):
        if _count(ring_health, key) != 0:
            blockers.append(f"{key}_nonzero")
    if _count(ring_health, "eligible_producer_receipt_count") != 0:
        blockers.append("unexpected_eligible_receipts_while_dark")
    return blockers


def _health_blockers(health: Mapping[str, Any]) -> list[str]:
    """The chain's own invariants: policy, outbox, orphans."""
    blockers: list[str] = []
    if health.get("readiness_contract_version") != READINESS_CONTRACT_VERSION:
        blockers.append("readiness_health_contract_mismatch")
    if _count(health, "active_consent_policy_count") != 1:
        blockers.append("active_consent_policy_count_invalid")
    if _count(health, "valid_active_consent_policy_count") != 1:
        blockers.append("product_legal_consent_configuration_invalid")
    zero_invariants = (
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
    if health.get("oldest_pending_confidence_outbox_at") is not None:
        blockers.append("unexpected_pending_outbox_timestamp")
    return blockers


def _downstream_state(
    health: Mapping[str, Any], *, dataset_creation_enabled: bool,
    training_enabled: bool, promotion_enabled: bool,
) -> dict[str, bool]:
    return {
        "dataset_creation": bool(dataset_creation_enabled)
        or health.get("dataset_creation_enabled") is not False,
        "training": bool(training_enabled)
        or health.get("training_enabled") is not False,
        "promotion": bool(promotion_enabled)
        or health.get("promotion_enabled") is not False,
    }


def assess_confidence_canary_readiness(
    health: Mapping[str, Any],
    *,
    cutover_mode: Any,
    ring_health: Mapping[str, Any],
    monitoring_enabled: bool,
    alert_sink_configured: bool,
    dataset_creation_enabled: bool,
    training_enabled: bool,
    promotion_enabled: bool,
) -> ConfidenceCanaryReadinessReport:
    """Fail closed unless every pre-activation gate has explicit evidence.

    ``health`` is ``get_mlc2_confidence_canary_readiness_v1`` (the chain's
    own orphan and outbox invariants); ``ring_health`` is
    ``get_ring_confidence_readiness_v1`` (the rows, the eligible
    principals, and the counts of receipts and canonical events written by
    anyone the row does NOT reach).
    """
    blockers: list[str] = []
    warnings: list[str] = []
    cutover = resolve_confidence_cutover(cutover_mode)

    if not cutover.valid_configuration:
        blockers.append("invalid_cutover_mode")
    elif cutover.mode != DARK:
        blockers.append("canary_must_remain_dark_during_readiness")
    blockers.extend(_ring_blockers(ring_health))
    if not monitoring_enabled:
        blockers.append("production_monitor_not_enabled")
    if not alert_sink_configured:
        blockers.append("production_alert_sink_not_configured")
    blockers.extend(_health_blockers(health))

    downstream = _downstream_state(
        health, dataset_creation_enabled=dataset_creation_enabled,
        training_enabled=training_enabled, promotion_enabled=promotion_enabled,
    )
    for capability, enabled in downstream.items():
        if enabled:
            blockers.append(f"{capability}_must_remain_disabled")

    eligible = _count(ring_health, "eligible_principal_count")
    if _count(ring_health, "eligible_producer_receipt_count") == 0:
        warnings.append("no_runtime_canary_receipt_expected_while_dark")
    if eligible > 1:
        warnings.append("more_than_one_ring_eligible_principal")

    evidence = {
        "cutover_mode": cutover.mode,
        "canonical_writes_enabled": cutover.canonical_writes_enabled,
        "prior_learning_writes_enabled": cutover.prior_learning_writes_enabled,
        "confidence_ring_feature": CONFIDENCE_RING_FEATURE,
        "confidence_ring_row_present": _flag(ring_health, "confidence_ring_row_present"),
        "confidence_ring_row_killed": _flag(ring_health, "confidence_ring_row_killed"),
        "canonical_take_rows_row_present": _flag(ring_health, "canonical_take_rows_row_present"),
        "canonical_take_rows_row_killed": _flag(ring_health, "canonical_take_rows_row_killed"),
        "ring_eligible_principal_count": eligible,
        "monitoring_enabled": bool(monitoring_enabled),
        "alert_sink_configured": bool(alert_sink_configured),
        "active_consent_policy_count": _count(
            health, "active_consent_policy_count"
        ),
        "valid_active_consent_policy_count": _count(
            health, "valid_active_consent_policy_count"
        ),
        "eligible_bundled_consent_grant_count": _count(
            ring_health, "eligible_bundled_consent_grant_count"
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
