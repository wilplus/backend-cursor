from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "tests" / "integration" /
       "mlc2_confidence_slice4_rehearsal.sql").read_text()


def test_slice4_rehearsal_rolls_back_and_keeps_app_flag_untouched():
    assert "\\set ON_ERROR_STOP on" in SQL
    assert "BEGIN;" in SQL
    assert SQL.rstrip().endswith("ROLLBACK;")
    assert "Config.MLC2_CONFIDENCE_CUTOVER_MODE" not in SQL
    prerequisite = (ROOT / "tests" / "integration" /
                    "mlc2_slice4_rehearsal_prerequisites.sql").read_text()
    assert "recording_attempts" in prerequisite
    assert "v2_sessions" in prerequisite
    assert "processing_jobs" in prerequisite


def test_slice4_rehearses_atomic_producer_blindness_and_monitoring():
    for boundary in (
        "promote_recording_attempt_with_mlc2_confidence_v1",
        "failed producer left partial product or outbox state",
        "producer replay was not effectively-once",
        "claim_mlc2_confidence_outbox_v1",
        "confidence worker leased another surface",
        "finalize_mlc2_confidence_frame_v1",
        "create_mlc2_confidence_blind_packet_v1",
        "blind packet leaked answer or selection hints",
        "ack_mlc2_rendered_exposure_v1",
        "submit_mlc2_confidence_blind_judgment_v1",
        "blind reveal unexpectedly succeeded before judgment",
        "get_mlc2_confidence_slice4_health_v1",
        "authenticated unexpectedly read blind packets",
    ):
        assert boundary in SQL
