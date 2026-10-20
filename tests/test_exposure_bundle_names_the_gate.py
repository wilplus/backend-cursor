"""
GUARD      A V3 Take whose feedback exposure bundle is not built logs the exact
           gate that closed (build_feedback_exposure_bundle's `detail` list),
           naming the condition, not just the step.
CATCHES    One reason name covering several unrelated conditions again: on
           2026-09-19 `exposure_bundle_membership_c...` covered seven, six of
           them not a count mismatch, and pointed the on-call reader at the
           wrong question.
IF REMOVED A missing-feedback incident can no longer be diagnosed from logs.
           Identifiers, families and counts only; nothing here reaches a
           speaker.
PROVES     test_a_row_with_neither_family_nor_key_still_names_its_slot
             a dropped candidate names itself (candidate_not_canonical)
           test_an_early_gate_names_its_own_condition
             unbuildable transcript and invalid keys each name themselves
"""
from __future__ import annotations

import unittest

from services.feedback_data_contract import (
    build_feedback_exposure_bundle,
)

TAKE = {
    "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    "project_id": "11111111-2222-4333-8444-555555555555",
    "owner_principal_id": "99999999-8888-4777-8666-555555555555",
    "take_index": 1,
}

# V3 requires a non-empty key list containing `confident_voice`, so the
# default fixture has to carry one to reach any gate past `selected_keys`.
KEYS = [{"id": "k1", "feedback_family": "confident_voice"}]

# A document whose transcript snapshot BUILDS, so the candidate loop is
# actually reached. The default fixture's empty `paragraphs` stops earlier.
WORDS = "Some words."
DOC = {
    "text": WORDS,
    "paragraphs": [{"start": 0, "end": len(WORDS), "slide_index": 0}],
}


def _gates(**overrides) -> list[str]:
    """The gates that closed for one call, in the order they closed."""
    detail: list[str] = []
    kwargs = {
        "session": TAKE,
        "transcript_document": {"text": "Some words.", "paragraphs": []},
        "served_text": "Some words.",
        "candidates": [],
        "selected_keys": KEYS,
        "manager_rules_version": "take-feedback-policy-v3-serving-v1",
        "detail": detail,
    }
    kwargs.update(overrides)
    assert build_feedback_exposure_bundle(**kwargs) is None
    return detail


class ADroppedCandidateNamesItself(unittest.TestCase):

    def test_a_row_with_neither_family_nor_key_still_names_its_slot(self):
        self.assertIn("candidate_not_canonical:∅/∅",
                      _gates(transcript_document=DOC, candidates=[{}]))

    def test_an_early_gate_names_its_own_condition(self):
        self.assertEqual(_gates(), ["transcript_snapshot_unbuildable"])
        self.assertEqual(_gates(selected_keys=[]), ["selected_keys_invalid"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
