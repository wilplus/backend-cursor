from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (
    ROOT / "tests" / "integration"
    / "mlc2_confidence_slice6_readiness.sql"
).read_text()


def test_slice6_rehearsal_is_disposable_and_does_not_activate_code():
    assert "\\set ON_ERROR_STOP on" in SQL
    assert "BEGIN;" in SQL
    assert SQL.rstrip().endswith("ROLLBACK;")
    assert "MLC2_CONFIDENCE_CUTOVER_MODE" not in SQL


def test_slice6_rehearses_consent_scope_monitoring_and_disabled_downstream():
    for boundary in (
        "record_mlc2_consent_grant_v1",
        "get_mlc2_confidence_canary_readiness_v1",
        "valid_active_consent_policy_count",
        "founder_active_bundled_consent_grant_count",
        "nonfounder_producer_receipt_count",
        "nonfounder_canonical_event_count",
        "pending_confidence_outbox_count",
        "dataset_creation_enabled",
        "training_enabled",
        "promotion_enabled",
        "has_function_privilege",
    ):
        assert boundary in SQL
