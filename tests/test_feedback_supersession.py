"""Machine-immediate → coach-superseded feedback invariants."""
from __future__ import annotations

import unittest

from services.star_verdicts import (
    released_user_verdicts,
)
from services.tracked_changes import build_coach_revision_changes

SID = "11111111-2222-3333-4444-555555555555"
TAKE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _accepted(**over):
    row = {
        "decision": "approved",
        "source": "user_star",
        "kind": "replace",
        "snippet_id": SID,
        "target_phrase": "original words",
        "display_phrase": "Original words",
        "replacement_text": "Machine accepted words",
        "version": 1,
    }
    row.update(over)
    return row


class CoachReleaseBoundaryTests(unittest.TestCase):
    def test_unpublished_coach_verdict_stays_private(self):
        verdicts = {SID: {"verdict": "should_not_fire"}}
        pieces = [{"snippet_id": SID, "take_session_id": TAKE}]
        sessions = [{"id": TAKE, "results_published_at": None}]
        self.assertEqual(released_user_verdicts(verdicts, pieces, sessions), {})


class CoachRevisionPinTests(unittest.TestCase):
    """build_coach_revision_changes, pinned before its split into named
    stages (audit W1, 2026-09-28): the exact change, which accepted row
    wins, and every way a revision is not offered."""

    DOC = "Alpha words here. Beta words here."

    def _accepted(self, sid, current, original, **over):
        row = {"decision": "approved", "source": "user_star",
               "kind": "replace", "snippet_id": sid,
               "replacement_text": current, "display_phrase": original,
               "updated_at": "2026-09-01T00:00:00Z", "version": 1}
        row.update(over)
        return row

    def _build(self, ledger, verdicts, suggestions=None, doc=None,
               pieces=None):
        return build_coach_revision_changes(
            self.DOC if doc is None else doc,
            [{"snippet_id": "b", "take_session_id": "t-b"},
             {"snippet_id": "a", "take_session_id": "t-a"}]
            if pieces is None else pieces,
            suggestions or {}, ledger, verdicts)

    def test_the_exact_change_and_the_order(self):
        out = self._build(
            [self._accepted("b", " Beta words ", "Old beta"),
             self._accepted("a", "Alpha words", "Old alpha")],
            {"a": {"verdict": "wrong_kind", "note": "Yours was right."},
             "b": {"verdict": "keep"}},
            {"b": {"replacement_text_final": " Coach beta ",
                   "why_final": None, "why": "machine why"}})
        self.assertEqual(out, [
            {"id": "coach-revision:a", "snippet_id": "a",
             "take_session_id": "t-a", "kind": "replace",
             "source": "coach_revision", "span": {"start": 0, "end": 11},
             "quote": "Alpha words", "proposed_text": "Old alpha",
             "coach_note": "Yours was right."},
            {"id": "coach-revision:b", "snippet_id": "b",
             "take_session_id": "t-b", "kind": "replace",
             "source": "coach_revision", "span": {"start": 18, "end": 28},
             "quote": "Beta words", "proposed_text": "Coach beta",
             "coach_note": "machine why"},
        ])


if __name__ == "__main__":
    unittest.main()
