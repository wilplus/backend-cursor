"""One answer vocabulary for owner responses (audit D2, 2026-09-28).

The answers an owner can give to a Feedback item were copied into three
modules, and one copy could gain or lose an answer without the others. They
now all come from ``services.canonical_product``; the narrower lists are
derived subsets, so a new answer is added once.
"""
from __future__ import annotations

from services.canonical_product import (
    JUDGEMENT_RESPONSES,
    OWNER_RESPONSES,
    SELF_REPORT_ONLY,
)


def test_the_vocabulary_is_exactly_what_the_copies_accepted():
    # Pinned literally: moving the lists here changed no accepted answer.
    assert {family: set(answers) for family, answers in OWNER_RESPONSES.items()} == {
        "confident_voice": {"yes", "in_between", "no", "not_sure", "audio_unclear"},
        "rewrite_clarity": {"apply_suggestion", "edit_myself", "keep_wording"},
        "great_formulation": {"useful", "not_useful", "not_sure", "acknowledged"},
    }


def test_the_take_response_validator_uses_the_one_vocabulary():
    from services.take_feedback_responses import RESPONSES

    assert RESPONSES is OWNER_RESPONSES


def test_judgements_are_the_owner_answers_minus_the_self_reports():
    for family, answers in OWNER_RESPONSES.items():
        assert JUDGEMENT_RESPONSES[family] == answers - SELF_REPORT_ONLY
    assert SELF_REPORT_ONLY <= set().union(*OWNER_RESPONSES.values())


def test_the_decision_map_covers_exactly_the_judgement_answers():
    from services.feedback_data_contract import _DECISION_MAP

    pairs = {(family, answer)
             for family, answers in JUDGEMENT_RESPONSES.items()
             for answer in answers}
    assert set(_DECISION_MAP) == pairs


def test_the_bundle_projection_accepts_only_judgement_answers():
    import inspect

    from services import confident_moment_bundle

    source = inspect.getsource(confident_moment_bundle.validate_family_response)
    assert "JUDGEMENT_RESPONSES" in source
    assert '"apply_suggestion"' not in source
