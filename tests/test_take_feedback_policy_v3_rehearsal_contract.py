from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRE = (ROOT / "tests" / "integration" /
       "take_feedback_policy_v3_prerequisites.sql").read_text()
REHEARSAL = (ROOT / "tests" / "integration" /
             "take_feedback_policy_v3_rehearsal.sql").read_text()
MIGRATION = (ROOT / "migrations" /
             "add_take_feedback_policy_v3_shadow.sql").read_text()
TRANSITION = (ROOT / "migrations" /
              "add_take_feedback_policy_universal_v3_transition.sql").read_text()


def test_rehearsal_is_disposable_and_has_exact_clip_fixture():
    assert "Never deploy this file" in PRE
    assert REHEARSAL.startswith("-- Transaction-scoped")
    assert "BEGIN;" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")
    assert "clip_identity_sha256" in REHEARSAL
    assert "mismatched clip interval was accepted" in REHEARSAL
    assert "incompatible detector artifact was accepted" in REHEARSAL
    assert "unrecomputed v2 clip was falsely marked recomputed" in REHEARSAL
    assert "excluded incompatible clip bypassed exact lineage" in REHEARSAL
    assert "voice-confidence-universal-v3" in REHEARSAL


def test_rpc_is_the_only_service_role_write_boundary():
    assert "GRANT SELECT ON TABLE" in MIGRATION
    assert "GRANT ALL ON TABLE" not in MIGRATION
    assert "has_table_privilege" in REHEARSAL
    assert "can bypass the validating RPC" in REHEARSAL
    assert "record_take_feedback_policy_v3_shadow_v3" in TRANSITION
    assert "incompatible_detector_version" in TRANSITION
    assert "REVOKE EXECUTE ON FUNCTION public.record_take_feedback_policy_v3_shadow_v2" in TRANSITION
    assert "replacement_frame_hash" in TRANSITION
    assert "CREATE OR REPLACE FUNCTION public.record_take_feedback_policy_v3_shadow_v2" not in TRANSITION
