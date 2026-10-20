"""
STORY    As the founder, I want to clear what waits on a blind list of the
         coach queue, so that it stays empty until next week's items come.
OUTCOME
  O1  A cleared item is never shown again.
  O2  A line cleared this week does not refill before next week, on each of
      the four lines.
PROVES   O1 -> FounderClearsABlindLineTests::test_a_cleared_item_is_never_shown_again
         O2 -> FounderClearsABlindLineTests::test_a_line_cleared_this_week_waits_for_next_week
WHY      Founder 2026-10-20: the ⋯ on Do you hear it?, Pick the most
         confident, Pick the moment for feedback and Which sounds surer
         ("New ones come next week. Answers already given stay."); 0482.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import coach_block_pick, error_presence_audit, v4_coach_sheets

WEEK = "2026-W43"
CLEARED = {"id": "s1", "take_session_id": "t1", "week": "2026-W42", "cleared_week": WEEK}


class FounderClearsABlindLineTests(unittest.TestCase):
    def test_a_cleared_item_is_never_shown_again(self):
        db = mock.Mock()
        db.list_v4_surer_sheets.return_value = [CLEARED]
        db.list_v4_pick_sheets.return_value = [CLEARED]
        self.assertEqual(v4_coach_sheets.surer_queue(db, rater_id="c1")[1]["items"], [])
        self.assertEqual(v4_coach_sheets.pick_queue(db, rater_id="c1")[1]["items"], [])

    def test_a_line_cleared_this_week_waits_for_next_week(self):
        db = mock.Mock()
        db.blind_line_cleared.return_value = True
        self.assertEqual(error_presence_audit.sample_for_coach(db, coach_id="c1"), [])
        self.assertEqual(coach_block_pick.sample_for_coach(db, coach_id="c1", week=WEEK), [])
        db.list_audit_candidates.assert_not_called()
        db.list_recent_v3_frames.assert_not_called()

        db.list_v4_surer_sheets.return_value = [CLEARED]
        db.list_v4_pick_sheets.return_value = [CLEARED]
        self.assertEqual(v4_coach_sheets.fill_surer_sheets(db, rater_id="c1", week=WEEK), [])
        self.assertEqual(v4_coach_sheets.fill_pick_sheets(db, rater_id="c1", week=WEEK), [])
        db.insert_v4_pick_sheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
