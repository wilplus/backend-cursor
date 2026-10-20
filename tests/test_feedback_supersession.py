"""
STORY    As a speaker, I want the machine's feedback straight away and the
         coach's revision only once the coach publishes, so that I never see
         an unreleased verdict.
OUTCOME
  O1  A coach verdict on an unpublished Take is hidden; on a published Take
      it is released, each judged against its own Take.
  O2  A released verdict becomes a coach_revision change against the words
      the speaker accepted, with the exact span, text and note.
PROVES   O1 -> test_only_verdicts_on_published_takes_are_released
         O2 -> test_the_exact_change_and_the_order
"""
from __future__ import annotations

import unittest

from services.star_verdicts import (
    released_user_verdicts,
)
from services.tracked_changes import build_coach_revision_changes

SID = "11111111-2222-3333-4444-555555555555"
TAKE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PUBLISHED_SID = "66666666-7777-8888-9999-000000000000"
PUBLISHED_TAKE = "ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee"


class CoachReleaseBoundaryTests(unittest.TestCase):
    def test_only_verdicts_on_published_takes_are_released(self):
        verdicts = {SID: {"verdict": "should_not_fire"},
                    PUBLISHED_SID: {"verdict": "wrong_kind", "note": "Yours was right."}}
        pieces = [{"snippet_id": SID, "take_session_id": TAKE},
                  {"snippet_id": PUBLISHED_SID, "take_session_id": PUBLISHED_TAKE}]
        sessions = [{"id": TAKE, "results_published_at": None},
                    {"id": PUBLISHED_TAKE,
                     "results_published_at": "2026-09-01T00:00:00Z"}]
        self.assertEqual(released_user_verdicts(verdicts, pieces, sessions), {
            PUBLISHED_SID: {"verdict": "wrong_kind", "note": "Yours was right."},
        })


class CoachRevisionPinTests(unittest.TestCase):
    """build_coach_revision_changes, pinned before its split into named
    stages (audit W1, 2026-09-28): the exact change and its order."""

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
