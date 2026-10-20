"""
STORY    As a speaker, I want the model's clearer rewrites to reach my
         feedback with their evidence, so that I get a rewrite where my
         wording was weak.
OUTCOME
  O1  A clearer version written because a read was weak (unconfident,
      stickiness, profanity) carries the Manager evidence naming that weak
      read, and the generator version; any other trigger carries none (and
      so stays excluded).
  O2  The evidence and the version never leave the server: the payload the
      speaker gets (strip_internal_evidence) keeps the rewrite and drops
      them (AC-9; Never rule 1, no numbers or verdicts shown to speakers).
PROVES   O1 -> test_a_clearer_version_carries_the_weak_read_behind_it
         O2 -> test_the_served_rewrite_carries_no_evidence
WHY      D-ML-3 (contract 24f, 25, 27, 29b; ledger A059a/A066): the model's
         clearer versions reached the Manager with no evidence, so V3
         excluded every one. V3's one-rewrite-per-weak-block selection is
         not pinned here.
"""
from __future__ import annotations

from services.take_feedback_manager import strip_internal_evidence
from services.tracked_changes import build_tracked_changes

SAID = "We give every learner a task that is short and daily."
DOC = "Hello all. " + SAID + " Thanks."
CLEARER = "We give every learner one short daily task."


def _clearer(trigger: str) -> list[dict]:
    """The tracked change the read path builds for one model clearer
    version on the piece the speaker said."""
    start = DOC.index(SAID)
    pieces = [{"snippet_id": "s1", "text": SAID, "start": start, "end": start + len(SAID)}]
    return build_tracked_changes(DOC, pieces, {"s1": {
        "kind": "replace", "trigger": trigger, "replacement_text": CLEARER,
        "why": "model prose the client never renders"}})


def test_a_clearer_version_carries_the_weak_read_behind_it():
    for trigger, basis in (("unconfident", "weak_delivery_read"),
                           ("stickiness", "weak_slide_fit_read"),
                           ("profanity", "profanity_read")):
        [row] = _clearer(trigger)
        assert row["proposed_text"] == CLEARER
        assert row["_manager_evidence"]["basis"] == basis
        assert row["_manager_evidence"]["read"] == "weak"
        assert row["suggestion_version"] == "moment-suggestion-clearer-v1"
    # The retired polish lane, or no trigger, earns no evidence.
    for trigger in ("polish", ""):
        rows = _clearer(trigger)
        assert all("_manager_evidence" not in row for row in rows)


def test_the_served_rewrite_carries_no_evidence():
    [served] = strip_internal_evidence(_clearer("unconfident"))
    assert served["proposed_text"] == CLEARER
    assert "_manager_evidence" not in served
    assert "suggestion_version" not in served
    assert "weak" not in repr(served)
