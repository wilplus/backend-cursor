from services.take_feedback_responses import (
    parse_feedback_response,
    validate_feedback_response,
)
from services.take_feedback_set import snippet_ids_by_family
from pathlib import Path
from services.db import DatabaseService
from tests.fakes import FakeSupabaseClient


KEYS = [
    {"id": "cv", "feedback_family": "confident_voice", "snippet_id": "s1"},
    {"id": "rw", "feedback_family": "rewrite_clarity", "snippet_id": "s2"},
    {"id": "pr", "feedback_family": "great_formulation", "snippet_id": "s3"},
]


def test_accepts_only_family_specific_responses_from_frozen_set():
    row, err = validate_feedback_response({
        "feedback_id": "cv",
        "feedback_family": "confident_voice",
        "response": "in_between",
        "snippet_id": "s1",
    }, KEYS)
    assert err is None
    assert row["response"] == "in_between"

    row, err = validate_feedback_response({
        "feedback_id": "pr",
        "feedback_family": "great_formulation",
        "response": "yes",
    }, KEYS)
    assert row is None
    assert "not valid" in err


def test_rejects_unexposed_identity_and_mismatched_clip_provenance():
    assert validate_feedback_response({
        "feedback_id": "new",
        "feedback_family": "rewrite_clarity",
        "response": "keep_wording",
    }, KEYS)[0] is None


def test_typed_parse_does_not_make_a_stale_membership_decision():
    row, err = parse_feedback_response({
        "feedback_id": "cv",
        "feedback_family": "confident_voice",
        "response": "yes",
        "snippet_id": "s1",
    })
    assert err is None
    assert row == {
        "feedback_id": "cv",
        "feedback_family": "confident_voice",
        "response": "yes",
        "snippet_id": "s1",
    }
    assert validate_feedback_response({
        "feedback_id": "cv",
        "feedback_family": "confident_voice",
        "response": "no",
        "snippet_id": "different",
    }, KEYS)[0] is None


def test_exact_canonical_identity_is_all_or_nothing_and_opaque():
    body = {
        "feedback_id": "rw",
        "feedback_family": "rewrite_clarity",
        "response": "apply_suggestion",
        "candidate_id": "11111111-1111-4111-8111-111111111111",
        "feedback_membership_id": "22222222-2222-4222-8222-222222222222",
        "feedback_exposure_id": "33333333-3333-4333-8333-333333333333",
    }
    row, err = parse_feedback_response(body)
    assert err is None
    assert row["candidate_id"] == body["candidate_id"]
    assert row["feedback_membership_id"] == body["feedback_membership_id"]
    assert row["feedback_exposure_id"] == body["feedback_exposure_id"]
    assert parse_feedback_response({
        **body, "feedback_exposure_id": None,
    })[0] is None
    assert parse_feedback_response({
        **body, "candidate_id": "not-a-uuid",
    })[0] is None

# ── merged from tests/test_take_feedback_set.py (audit Q-T9) ──

def test_snippet_ids_by_family_reads_only_sanitized_frozen_membership():
    keys = [
        {
            "id": "rewrite-review:one",
            "kind": "replace",
            "source": "wording",
            "feedback_family": "rewrite_clarity",
            "snippet_id": "frozen-rewrite",
        },
        {
            "id": "praise-review:one",
            "kind": "advice",
            "source": "structural",
            "feedback_family": "great_formulation",
            "snippet_id": "frozen-praise",
        },
    ]

    assert snippet_ids_by_family(keys) == {
        "rewrite_clarity": "frozen-rewrite",
        "great_formulation": "frozen-praise",
    }

# ── merged from tests/test_atomic_take_feedback_response.py (audit Q-T9) ──

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


# ---------------------------------------------------------------------------
#  "acknowledged" — praise is read, not rated (0333, founder 2026-09-15)
#
#  The praise screen offers one Continue instead of Useful / Not useful / Not
#  sure. The write it makes is what marks the item decided; drop it and praise
#  is re-offered every time the paragraph opens, forever. So Continue writes an
#  ACKNOWLEDGEMENT rather than a verdict.
# ---------------------------------------------------------------------------


def test_praise_accepts_an_acknowledgement():
    row, err = parse_feedback_response({
        "feedback_id": "pr",
        "feedback_family": "great_formulation",
        "response": "acknowledged",
    })
    assert err is None, err
    assert row["response"] == "acknowledged"


def test_the_ratings_still_work_for_surfaces_that_rate():
    for value in ("useful", "not_useful", "not_sure"):
        _, err = parse_feedback_response({
            "feedback_id": "pr",
            "feedback_family": "great_formulation",
            "response": value,
        })
        assert err is None, value


def test_acknowledged_belongs_to_praise_alone():
    # It is not a confidence answer and not a correction decision; letting it
    # through on another family would put a non-answer in a typed lane.
    for family in ("confident_voice", "rewrite_clarity"):
        _, err = parse_feedback_response({
            "feedback_id": "x",
            "feedback_family": family,
            "response": "acknowledged",
        })
        assert err is not None, family


def test_an_acknowledgement_never_becomes_a_praise_helpfulness_label():
    """The point of the whole design.

    praise_helpfulness holds a judgement on a scale. "I read this" is not a
    point on that scale, so no canonical decision is produced at all — exactly
    as `edit_myself` produces none. The database agrees: the canonical praise
    guards RAISE on an unknown value rather than skipping, so a mapping here
    would have turned every Continue into a 500.
    """
    from services.feedback_data_contract import (
        _DECISION_MAP,
        canonical_feedback_decision,
    )

    assert ("great_formulation", "acknowledged") not in _DECISION_MAP
    assert ("rewrite_clarity", "edit_myself") not in _DECISION_MAP
    assert canonical_feedback_decision(
        take_id="11111111-1111-4111-8111-111111111111",
        rater_id="22222222-2222-4222-8222-222222222222",
        feedback_id="pr",
        feedback_family="great_formulation",
        response="acknowledged",
        candidate_id="33333333-3333-4333-8333-333333333333",
        feedback_membership_id="44444444-4444-4444-8444-444444444444",
        feedback_exposure_id="55555555-5555-4555-8555-555555555555",
    ) is None


def test_both_owner_gates_widened_together():
    """The table CHECK and the function guard must agree.

    They are separate gates on the same write, so widening one alone fails at
    whichever is stricter — and the failure would only appear in production,
    on the first Continue.
    """
    sql = (Path(__file__).resolve().parents[1]
           / "migrations" / "add_acknowledged_praise_response.sql").read_text()
    assert "take_feedback_self_report_response" in sql
    assert sql.count(
        "'useful', 'not_useful', 'not_sure', 'acknowledged'") == 2
    # Reproduced from 0308 rather than hand-retyped: the function must still
    # be the same function.
    assert "record_take_feedback_response_v1" in sql
    assert "DROP CONSTRAINT IF EXISTS" in sql


def test_the_canonical_praise_scale_is_left_alone():
    # If a later change widens praise_helpfulness to hold 'acknowledged', the
    # scale stops being a scale. This is the guard on that.
    root = Path(__file__).resolve().parents[1]
    for name in ("add_canonical_feedback_data_contract.sql",
                 "add_confident_moment_coaching_bundle_v1.sql"):
        sql = (root / "migrations" / name).read_text()
        assert "acknowledged" not in sql, name
