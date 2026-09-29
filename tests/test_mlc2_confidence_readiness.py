from pathlib import Path

import pytest

from services.mlc2_confidence_readiness import (
    READINESS_CONTRACT_VERSION,
    RING_READINESS_CONTRACT_VERSION,
    assess_confidence_canary_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
FOUNDER_PRINCIPAL = "11111111-1111-4111-8111-111111111111"


def _health() -> dict:
    return {
        "readiness_contract_version": READINESS_CONTRACT_VERSION,
        "active_consent_policy_count": 1,
        "valid_active_consent_policy_count": 1,
        "pending_confidence_outbox_count": 0,
        "failed_confidence_outbox_count": 0,
        "oldest_pending_confidence_outbox_at": None,
        "receipt_without_outbox_count": 0,
        "processed_without_frame_count": 0,
        "blind_assignment_without_packet_count": 0,
        "revealed_without_judgment_count": 0,
        "dataset_creation_enabled": False,
        "training_enabled": False,
        "promotion_enabled": False,
    }


def _ring_health() -> dict:
    """get_ring_confidence_readiness_v1 with one ring-eligible principal
    (the founder) and nobody the row does not reach having written."""
    return {
        "ring_readiness_contract_version": RING_READINESS_CONTRACT_VERSION,
        "confidence_ring_row_present": True,
        "confidence_ring_row_killed": False,
        "confidence_ring_row_one_way": True,
        "canonical_take_rows_row_present": True,
        "canonical_take_rows_row_killed": False,
        "eligible_principal_count": 1,
        "eligible_bundled_consent_grant_count": 1,
        "eligible_producer_receipt_count": 0,
        "noneligible_producer_receipt_count": 0,
        "noneligible_canonical_event_count": 0,
    }


def _assess(health: dict | None = None, ring_health: dict | None = None, **overrides):
    inputs = {
        "cutover_mode": "dark",
        "ring_health": ring_health if ring_health is not None else _ring_health(),
        "monitoring_enabled": True,
        "alert_sink_configured": True,
        "dataset_creation_enabled": False,
        "training_enabled": False,
        "promotion_enabled": False,
    }
    inputs.update(overrides)
    return assess_confidence_canary_readiness(health or _health(), **inputs)


def test_all_pre_activation_evidence_can_be_ready_while_cutover_stays_dark():
    report = _assess()
    assert report.ready is True
    assert report.blocker_codes == ()
    assert report.evidence["canonical_writes_enabled"] is False
    assert report.evidence["prior_learning_writes_enabled"] is True


def test_founder_canary_is_the_flipped_state_and_the_monitor_keeps_guarding():
    """The flip (founder 2026-09-29): the same invariants hold, canonical
    writes are on for the reached and consented person, and the receipt
    warning no longer says "while dark"."""
    report = _assess(cutover_mode="founder_canary")
    assert report.ready is True
    assert report.blocker_codes == ()
    assert report.evidence["canonical_writes_enabled"] is True
    assert report.evidence["prior_learning_writes_enabled"] is False
    assert "no_runtime_canary_receipt_yet" in report.warning_codes
    assert "no_runtime_canary_receipt_expected_while_dark" not in report.warning_codes


@pytest.mark.parametrize(
    "override,blocker",
    [
        ({"cutover_mode": "killed"}, "canary_killed"),
        ({"cutover_mode": "typo"}, "invalid_cutover_mode"),
        ({"source_audio_store_is_r2": False},
         "confidence_source_audio_store_not_r2"),
        ({"monitoring_enabled": False},
         "production_monitor_not_enabled"),
        ({"alert_sink_configured": False},
         "production_alert_sink_not_configured"),
        ({"dataset_creation_enabled": True},
         "dataset_creation_must_remain_disabled"),
        ({"training_enabled": True}, "training_must_remain_disabled"),
        ({"promotion_enabled": True}, "promotion_must_remain_disabled"),
    ],
)
def test_configuration_gates_fail_closed(override, blocker):
    report = _assess(**override)
    assert report.ready is False
    assert blocker in report.blocker_codes


@pytest.mark.parametrize(
    "health_key,blocker",
    [
        ("valid_active_consent_policy_count",
         "product_legal_consent_configuration_invalid"),
        ("failed_confidence_outbox_count",
         "failed_confidence_outbox_count_nonzero"),
        ("receipt_without_outbox_count",
         "receipt_without_outbox_count_nonzero"),
        ("processed_without_frame_count",
         "processed_without_frame_count_nonzero"),
        ("blind_assignment_without_packet_count",
         "blind_assignment_without_packet_count_nonzero"),
        ("revealed_without_judgment_count",
         "revealed_without_judgment_count_nonzero"),
    ],
)
def test_database_evidence_gates_fail_closed(health_key, blocker):
    health = _health()
    health[health_key] = 0 if "consent" in health_key else 1
    report = _assess(health)
    assert report.ready is False
    assert blocker in report.blocker_codes


@pytest.mark.parametrize(
    "override,blocker",
    [
        ({"ring_readiness_contract_version": "other"},
         "ring_readiness_contract_mismatch"),
        ({"confidence_ring_row_present": False}, "confidence_ring_row_missing"),
        ({"confidence_ring_row_killed": True}, "confidence_ring_row_killed"),
        ({"confidence_ring_row_one_way": False},
         "confidence_ring_row_not_one_way"),
        ({"canonical_take_rows_row_present": False},
         "canonical_take_rows_row_missing"),
        ({"canonical_take_rows_row_killed": True},
         "canonical_take_rows_row_killed"),
        ({"eligible_principal_count": 0}, "no_ring_eligible_principal"),
        ({"eligible_bundled_consent_grant_count": 0},
         "eligible_bundled_consent_missing"),
        ({"noneligible_producer_receipt_count": 1},
         "noneligible_producer_receipt_count_nonzero"),
        ({"noneligible_canonical_event_count": 1},
         "noneligible_canonical_event_count_nonzero"),
        ({"eligible_producer_receipt_count": 1},
         "unexpected_eligible_receipts_while_dark"),
    ],
)
def test_ring_evidence_gates_fail_closed(override, blocker):
    """The canary's "who" is the ring row (0394): the row must exist, be
    one-way and not killed, reach at least one principal with a bundled
    consent grant, and nobody the row does NOT reach may have written a
    receipt or a canonical event."""
    ring_health = {**_ring_health(), **override}
    report = _assess(ring_health=ring_health)
    assert report.ready is False
    assert blocker in report.blocker_codes


def test_readiness_no_longer_reads_the_retired_canary_variables():
    """Neither the founder email nor the principal variable decides anything
    here any more; the ring row and the ring health do."""
    source = (ROOT / "services" / "mlc2_confidence_readiness.py").read_text()
    script = (
        ROOT / "scripts" / "check_mlc2_confidence_canary_readiness.py"
    ).read_text()
    for retired in ("MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL",
                    "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID",
                    "DATA_FOUNDATION_CANARY_ENABLED", "APPROVED_FOUNDER_EMAIL"):
        assert retired not in source
        assert retired not in script
    assert "get_ring_confidence_readiness_v1" in script
    assert "ring_health=" in script


def test_readiness_monitor_is_aggregate_only_and_not_a_product_route():
    migration = (
        ROOT / "migrations" / "add_mlc2_confidence_canary_readiness.sql"
    ).read_text()
    script = (
        ROOT / "scripts" / "check_mlc2_confidence_canary_readiness.py"
    ).read_text()
    for forbidden in ("transcript", "visible_packet", "audio_bytes"):
        assert forbidden not in migration.lower()
        assert forbidden not in script.lower()
    route_sources = "\n".join(
        path.read_text() for path in (ROOT / "routes").rglob("*.py")
    )
    assert "get_mlc2_confidence_canary_readiness_v1" not in route_sources


def test_railway_monitor_is_recurring_read_only_and_alerting():
    cron = (
        ROOT / "bin" / "railway-mlc2-confidence-readiness-cron.sh"
    ).read_text()
    assert "*/5 * * * *" in cron
    assert "check_mlc2_confidence_canary_readiness.py --json --alert" in cron
    assert "MLC2_CONFIDENCE_MONITORING_ENABLED=true" in cron
    assert "founder_canary" not in cron


def test_normal_feedback_selection_precedes_and_does_not_depend_on_writer_gate():
    # The `changes` block moved out of the route in Phase 5 (audit Q-C1).
    # Its orchestrator (`_ChangesRun.execute`) claims and filters first,
    # then reads the writer gate, then — and only then — dual-writes.
    import inspect
    from services.ideal_text_changes import _ChangesRun
    execute = inspect.getsource(_ChangesRun.execute)
    claim = execute.index("self._claim_or_filter()")
    writer_gate = execute.index("confidence_prior_learning_writes_enabled()")
    write = execute.index("self._canonical_dual_write", writer_gate)
    assert claim < writer_gate < write
    claim_stage = inspect.getsource(_ChangesRun._claim_or_filter)
    assert "self.feedback_set = claim_feedback_set(" in claim_stage
    assert "self.changes = filter_to_selected(" in claim_stage
    assert "confidence_prior_learning_writes_enabled" not in claim_stage
    write_stage = inspect.getsource(_ChangesRun._canonical_dual_write)
    assert "db.record_canonical_feedback_exposure(" in write_stage
