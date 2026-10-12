"""D-ML-3: the rewrite lane fills.

Contract 24f, 25, 27, 29b; ledger A059a / A066. The model's own clearer
versions (`moment_suggestions`, the replace kind) reached the Manager with no
`_manager_evidence` and no generator version, so V3 excluded every one
(`missing_evidence_metadata`) and the rewrite lane was one structural rule
plus a tentative fallback. Each clearer version now carries the weak read
that made the generator write it, named by a reason from a fixed, versioned
list, and the generator version this reader vouches for.

What does NOT change: V3 still anchors at most one rewrite per block read
weak, only where its words are this Take's (L2); a lane with nothing
defensible stays an honest `no_defensible_candidate` (contract 25); the
evidence never leaves the server (AC-9); and no user-facing word is added.
"""
from __future__ import annotations

from services.intervention_candidates import feedback_family_of
from services.tracked_changes import (
    CLEARER_VERSION_REASONS,
)
from tests.test_verbal_lanes_take_document_n48_1 import (
    _tracked,
)

CLEARER = "We give every learner one short daily task."


def _clearer(trigger: str = "unconfident", sid: str = "s1b",
             replacement: str = CLEARER) -> dict:
    """The served row for one model clearer version, as the read path
    builds it (`build_tracked_changes`, then the family)."""
    [row] = _tracked({"kind": "replace", "trigger": trigger,
                      "replacement_text": replacement,
                      "why": "model prose the client never renders"}, sid)
    row["feedback_family"] = feedback_family_of(row)
    return row


class TestAClearerVersionCarriesItsEvidence:

    def test_every_reason_comes_from_the_fixed_list(self):
        for trigger, reason in CLEARER_VERSION_REASONS.items():
            row = _clearer(trigger)
            assert row["_manager_evidence"]["basis"] == reason
        assert set(CLEARER_VERSION_REASONS) == {
            "unconfident", "stickiness", "profanity"}
