from pathlib import Path

import pytest

from services.mlc2_confidence_readiness import (
    READINESS_CONTRACT_VERSION,
    assess_confidence_canary_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
FOUNDER_PRINCIPAL = "11111111-1111-4111-8111-111111111111"


def _health() -> dict:
    return {
        "readiness_contract_version": READINESS_CONTRACT_VERSION,
        "founder_principal_configured": True,
        "active_consent_policy_count": 1,
        "valid_active_consent_policy_count": 1,
        "founder_active_bundled_consent_grant_count": 1,
        "founder_producer_receipt_count": 0,
        "nonfounder_producer_receipt_count": 0,
        "nonfounder_canonical_event_count": 0,
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


def _assess(health: dict | None = None, **overrides):
    inputs = {
        "cutover_mode": "dark",
        "configured_founder_email": "artur@willonski.com",
        "founder_principal_id": FOUNDER_PRINCIPAL,
        "data_foundation_canary_enabled": True,
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


@pytest.mark.parametrize(
    "override,blocker",
    [
        ({"cutover_mode": "founder_canary"},
         "canary_must_remain_dark_during_readiness"),
        ({"cutover_mode": "typo"}, "invalid_cutover_mode"),
        ({"configured_founder_email": "other@example.com"},
         "founder_email_scope_mismatch"),
        ({"founder_principal_id": ""},
         "founder_principal_not_configured"),
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
        ("founder_active_bundled_consent_grant_count",
         "founder_bundled_consent_missing"),
        ("nonfounder_producer_receipt_count",
         "nonfounder_producer_receipt_count_nonzero"),
        ("nonfounder_canonical_event_count",
         "nonfounder_canonical_event_count_nonzero"),
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


def test_normal_feedback_selection_precedes_and_does_not_depend_on_writer_gate():
    route = (ROOT / "routes" / "v2" / "explore_ideal_text.py").read_text()
    claim = route.index("_feedback_set = claim_feedback_set(")
    writer_gate = route.index("confidence_prior_learning_writes_enabled()")
    write = route.index("db.record_canonical_feedback_exposure(", writer_gate)
    assert claim < writer_gate < write
    assert "changes = filter_to_selected" in route[claim:writer_gate]
