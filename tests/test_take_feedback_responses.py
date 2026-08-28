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
