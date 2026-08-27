from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "tests" / "integration" /
       "mlc2_foundation_rehearsal.sql").read_text(encoding="utf-8")


def test_rehearsal_is_fail_closed_and_rolls_back_fixtures():
    assert "\\set ON_ERROR_STOP on" in SQL
    assert "BEGIN;" in SQL
    assert SQL.rstrip().endswith("ROLLBACK;")


def test_rehearsal_covers_foundation_security_and_rpc_boundaries():
    required = (
        "register_ml_speaker_principal_v1",
        "record_mlc2_consent_grant_v1",
        "record_mlc2_consent_withdrawal_v1",
        "create_mlc2_consent_snapshot_v1",
        "enqueue_mlc2_outbox_event_v1",
        "claim_mlc2_outbox_events_v1",
        "finalize_mlc2_outbox_event_v1",
        "fail_mlc2_outbox_event_v1",
        "ack_mlc2_rendered_exposure_v1",
        "reveal_ml_review_assignment_v1",
        "relrowsecurity",
        "role_table_grants",
        "routine_privileges",
    )
    for boundary in required:
        assert boundary in SQL


def test_rehearsal_pins_dark_contract_counts_and_blindness_checks():
    assert "ml_table_count <> 29" in SQL
    assert "count(*) FROM public.ml_learning_surfaces) <> 7" in SQL
    assert "blind reveal unexpectedly succeeded before submission" in SQL
    assert "shadow render acknowledgement unexpectedly succeeded" in SQL
    assert "outbox finalization was not effectively-once" in SQL
    assert "snapshot unexpectedly succeeded after withdrawal" in SQL
