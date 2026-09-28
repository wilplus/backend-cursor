"""One rewrite family, two stored spellings (audit B2, 2026-09-28).

The coach-review lineage stores `rewrite_for_clarity`; the Take-feedback
lineage (V3, Confident Moment bundles) stores `rewrite_clarity`. Before this
change `FeedbackFamily("rewrite_clarity")` raised, and the coach-feedback
reader turned any family it could not parse into Great Formulation, i.e.
praise, without a word.
"""
from __future__ import annotations

import pytest

from services.canonical_product import FeedbackFamily
from services.feedback_repository import FeedbackContractError, _family


def test_both_spellings_read_as_the_one_rewrite_family():
    assert FeedbackFamily("rewrite_clarity") is FeedbackFamily.REWRITE_FOR_CLARITY
    assert FeedbackFamily("rewrite_for_clarity") is FeedbackFamily.REWRITE_FOR_CLARITY
    # What gets written back is the coach-review spelling its CHECK allows.
    assert FeedbackFamily("rewrite_clarity").value == "rewrite_for_clarity"


def test_other_unknown_values_still_raise():
    with pytest.raises(ValueError):
        FeedbackFamily("rewrite")


def test_a_stated_rewrite_is_never_read_as_praise():
    assert _family({"feedback_family": "rewrite_clarity"}) is (
        FeedbackFamily.REWRITE_FOR_CLARITY)


def test_an_unknown_stated_family_is_a_contract_error_not_praise():
    with pytest.raises(FeedbackContractError, match="unknown feedback family"):
        _family({"feedback_family": "rewrite_clarity_v2"})


def test_a_legacy_note_without_a_family_keeps_its_old_reading():
    assert _family({"tag": "to_work_on"}) is FeedbackFamily.REWRITE_FOR_CLARITY
    assert _family({"tag": "strong"}) is FeedbackFamily.GREAT_FORMULATION
    assert _family({}) is FeedbackFamily.GREAT_FORMULATION
    assert _family({"feedback_family": None}) is FeedbackFamily.GREAT_FORMULATION


def test_a_row_with_an_unknown_family_is_skipped_and_logged(caplog):
    # Not praise, and not a failed read for the other items on the Take.
    from unittest.mock import patch

    from services.feedback_repository import FeedbackRepository
    from tests.test_feedback_repository import DOCUMENT, FakeDatabase

    database = FakeDatabase(family="rewrite_clarity_v2")
    with patch("services.transcript_document.build_transcript_document",
               return_value=DOCUMENT), caplog.at_level("ERROR"):
        items = FeedbackRepository(database).surfaced_items("take-1")
    assert items == []
    assert "unknown feedback family" in caplog.text
