from pathlib import Path

from services.db import DatabaseService
from tests.fakes import FakeSupabaseClient


ROUTE = Path("routes/v2/explore_ideal_text.py").read_text()
MIGRATION = Path("migrations/add_take_feedback_policy_v3_shadow.sql").read_text()


def test_shadow_is_wired_but_cannot_become_the_serving_path():
    assert "dark_enabled(_v3_principal_id)" in ROUTE
    assert "record_take_feedback_policy_v3_shadow" in ROUTE
    assert "serves_user_feedback" in MIGRATION
    assert "CHECK (rendered_exposure_id IS NULL)" in MIGRATION
    assert "CHECK (dataset_eligible = FALSE)" in MIGRATION
    assert "acquisition_principal_id" in MIGRATION
    assert "take_row.owner_principal_id IS DISTINCT FROM" in MIGRATION
    assert "take_row.recording_1_id IS DISTINCT FROM p_recording_id" in MIGRATION
    assert "LEFT JOIN public.snippets" in MIGRATION
    assert "GRANT SELECT ON TABLE" in MIGRATION
    assert "GRANT ALL ON TABLE" not in MIGRATION


def test_database_adapter_uses_the_service_only_atomic_rpc():
    client = FakeSupabaseClient(rpc_rows={
        "record_take_feedback_policy_v3_shadow_v2": [{
            "outcome": "stored",
            "frame_hash": "a" * 64,
        }],
    })
    database = DatabaseService.__new__(DatabaseService)
    database.client = client
    result = database.record_take_feedback_policy_v3_shadow(
        arc_id="arc",
        take_session_id="11111111-1111-4111-8111-111111111111",
        recording_id="44444444-4444-4444-8444-444444444444",
        acquisition_principal_id="33333333-3333-4333-8333-333333333333",
        owner_user_id="22222222-2222-4222-8222-222222222222",
        take_index=2,
        policy_version="take-feedback-policy-v3-dark-v2",
        frame={"serves_user_feedback": False, "dataset_eligible": False},
        frame_hash="a" * 64,
    )
    assert result["outcome"] == "stored"
    assert client.tables == {}
    assert "record_take_feedback_policy_v3_shadow_v2" in client.rpcs
    payload = client.rpcs["record_take_feedback_policy_v3_shadow_v2"].payload
    assert payload["p_recording_id"] == (
        "44444444-4444-4444-8444-444444444444"
    )
