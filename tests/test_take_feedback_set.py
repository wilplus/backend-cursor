from services.take_feedback_set import snippet_ids_by_family


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
