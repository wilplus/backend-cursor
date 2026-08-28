from pathlib import Path

from services.db import DatabaseService

from tests.fakes import FakeSupabaseClient


MIGRATION = Path("migrations/add_atomic_take_feedback_response.sql").read_text()


def test_atomic_rpc_owns_membership_idempotency_and_provenance():
    for token in (
        "FROM public.ideal_text_feedback_sets",
        "jsonb_array_elements(selected)",
        "FROM public.take_feedback_self_report",
        "ON CONFLICT (take_session_id, owner_user_id, feedback_id) DO NOTHING",
        "'outcome', 'replayed'",
        "'outcome', 'provenance_mismatch'",
    ):
        assert token in MIGRATION


def test_database_writer_uses_only_the_atomic_rpc():
    client = FakeSupabaseClient(rpc_rows={
        "record_take_feedback_response_v1": [{
            "outcome": "saved",
            "row": {"feedback_id": "item-1", "response": "yes"},
            "selected_keys": [],
        }],
    })
    database = DatabaseService.__new__(DatabaseService)
    database.client = client

    result = database.insert_take_feedback_self_report(
        arc_id="arc-1",
        take_session_id="11111111-1111-4111-8111-111111111111",
        owner_user_id="22222222-2222-4222-8222-222222222222",
        feedback_id="item-1",
        feedback_family="confident_voice",
        response="yes",
        snippet_id="33333333-3333-4333-8333-333333333333",
    )

    assert result["outcome"] == "saved"
    assert client.tables == {}
    call = client.rpcs["record_take_feedback_response_v1"].calls[0]
    assert call[1][1]["p_feedback_id"] == "item-1"
