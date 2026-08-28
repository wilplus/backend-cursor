from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRE = (ROOT / "tests" / "integration" /
       "take_feedback_policy_v3_prerequisites.sql").read_text()
REHEARSAL = (ROOT / "tests" / "integration" /
             "take_feedback_policy_v3_rehearsal.sql").read_text()
MIGRATION = (ROOT / "migrations" /
             "add_take_feedback_policy_v3_shadow.sql").read_text()


def test_rehearsal_is_disposable_and_has_exact_clip_fixture():
    assert "Never deploy this file" in PRE
    assert REHEARSAL.startswith("-- Transaction-scoped")
    assert "BEGIN;" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")
    assert "clip_identity_sha256" in REHEARSAL
    assert "mismatched clip interval was accepted" in REHEARSAL


def test_rpc_is_the_only_service_role_write_boundary():
    assert "GRANT SELECT ON TABLE" in MIGRATION
    assert "GRANT ALL ON TABLE" not in MIGRATION
    assert "has_table_privilege" in REHEARSAL
    assert "can bypass the validating RPC" in REHEARSAL
