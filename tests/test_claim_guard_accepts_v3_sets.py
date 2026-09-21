"""The client-side freeze guard accepts what the database accepts.

FOUNDER 2026-09-21, project C, fresh Take under enforce: "still no
bookmarks". The backend log had the whole story in three lines —
``first_client: v3 served items=4``, then ``feedback set claim failed``,
then ``feedback_set_claim degraded (claim_failed)`` — and the page got an
empty block. Migration 0347 taught the SQL function and
``services.take_feedback_set`` V3's rule (a bounded set carrying a Confident
Voice item), but ``DatabaseService.claim_ideal_text_feedback_set`` still
demanded V2's exactly-three-families and returned None without calling the
database at all. These pin that the guard now mirrors the function.
"""
from services.db import DatabaseService
from tests.fakes import FakeSupabaseClient

ARC = "11111111-1111-1111-1111-111111111111"
OWNER = "22222222-2222-2222-2222-222222222222"
TAKE = "33333333-3333-3333-3333-333333333333"


def _key(family: str, n: int) -> dict:
    return {"id": f"item-{n}", "kind": "bold", "source": "v3",
            "feedback_family": family, "snippet_id": f"snip-{n}"}


def _v3_set() -> list:
    # One Confident Voice item per block over three blocks, one praise: four.
    return [_key("confident_voice", 1), _key("confident_voice", 2),
            _key("confident_voice", 3), _key("great_formulation", 4)]


def _service(rpc_rows=None) -> DatabaseService:
    service = DatabaseService.__new__(DatabaseService)
    service.client = FakeSupabaseClient(rpc_rows=rpc_rows)
    return service


def _winner(keys: list) -> dict:
    return {"arc_id": ARC, "take_session_id": TAKE, "take_index": 2,
            "review_version": 2, "selected_keys": keys}


def test_a_four_item_v3_set_reaches_the_database():
    keys = _v3_set()
    service = _service({"claim_ideal_text_feedback_set_v1": [_winner(keys)]})
    row = service.claim_ideal_text_feedback_set(ARC, OWNER, TAKE, 2, 2, keys)
    assert row is not None and row["selected_keys"] == keys
    sent = service.client.rpcs["claim_ideal_text_feedback_set_v1"].payload
    assert sent["p_selected_keys"] == keys


def test_v2s_three_families_still_freeze():
    keys = [_key("confident_voice", 1), _key("rewrite_clarity", 2),
            _key("great_formulation", 3)]
    service = _service({"claim_ideal_text_feedback_set_v1": [_winner(keys)]})
    assert service.claim_ideal_text_feedback_set(
        ARC, OWNER, TAKE, 2, 2, keys) is not None


def test_a_set_without_confident_voice_never_reaches_the_database():
    keys = [_key("rewrite_clarity", 1), _key("great_formulation", 2)]
    service = _service()
    assert service.claim_ideal_text_feedback_set(
        ARC, OWNER, TAKE, 2, 2, keys) is None
    assert "claim_ideal_text_feedback_set_v1" not in service.client.rpcs


def test_the_storage_ceiling_is_the_migrations_ceiling():
    from services.take_feedback_set import MAX_SELECTED_KEYS
    keys = [_key("confident_voice", n) for n in range(MAX_SELECTED_KEYS + 1)]
    service = _service()
    assert service.claim_ideal_text_feedback_set(
        ARC, OWNER, TAKE, 2, 2, keys) is None
    assert "claim_ideal_text_feedback_set_v1" not in service.client.rpcs


def test_the_exposure_record_takes_a_v3_selection_too():
    keys = _v3_set()
    service = _service()
    ok = service.insert_take_feedback_exposure(
        arc_id=ARC, take_session_id=TAKE, review_version=2,
        policy_version="v3", candidate_set=[dict(k) for k in keys],
        selected_keys=keys)
    assert ok is True
    assert "take_feedback_exposure" in service.client.tables
