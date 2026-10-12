"""Seven conditions had one name, and six of them were not a count mismatch.

PRODUCTION, 2026-09-19, minutes after #568. The founder's take got past
``service_inventory_unavailable`` for the first time since the V3 cutover --
the binder logged ``placed=4/4 parts=3``, so every spoken piece finally knew
its Paragraph -- and stood down one gate later:

    first_client: v3 stood down reason=exposure_bundle_membership_c…

That reason covered SEVEN separate conditions: the six ``return None`` exits
inside ``build_feedback_exposure_bundle`` and the caller's own membership-count
check. Six of them have nothing to do with a count, so the one name the log
offered was not merely vague, it pointed the reader at the wrong question.

This is the fourth time in one day that a typed reason named a STEP instead of
a CONDITION (``_row_rejection``'s ten, ``prepare_v3_service_inventory``'s six,
``_decline``'s clipped ordering, and now this). The fix is the same one that
worked three times: pass a ``detail`` list, append the gate that closed, and
split the caller's single reason into the two things it actually meant.

WHAT THIS IS NOT. It does not weaken the complete-inventory invariant. #567
excluded rows that could not be PROVEN, at the policy layer, before anything
was written; this is the write itself, and a bundle that quietly omits a row
it was handed is an audit record that lies about what the service considered.
The invariant stays -- it just says the counts out loud now.

AC-9 is untouched: none of this reaches a user. Identifiers, families and
counts only -- never a candidate's words, never a score.
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

# A document whose transcript snapshot BUILDS, so the candidate loop below is
# actually reached. The default fixture's empty `paragraphs` stops one gate
# earlier, which is its own test above.
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
    build_feedback_exposure_bundle(**kwargs)
    return detail


class ADroppedCandidateNamesItself(unittest.TestCase):

    def test_a_row_with_neither_family_nor_key_still_names_its_slot(self):
        self.assertIn("candidate_not_canonical:∅/∅",
                      _gates(transcript_document=DOC, candidates=[{}]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
