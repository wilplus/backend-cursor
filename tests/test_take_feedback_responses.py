from services.take_feedback_responses import (
    parse_feedback_response,
    validate_feedback_response,
)


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
