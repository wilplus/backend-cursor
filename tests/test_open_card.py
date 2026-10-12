"""The card the page opens a moment on (founder 2026-10-05, N48.1, Wave 1
step 1).

The follow-up matrix decides at the open what shows (`decide_at_open`), but
the page chose its card itself and, never told whether a problem fired
(AC-9), showed the rewrite where the matrix says the coach's request. The
served moment now carries `open_card`, computed by the same `decide_at_open`
from the same clip read and exercise draw `follow_up_for_open` uses. Pins:
one value per matrix cell; a closed enum and nothing else rides the row; the
field is omitted when the inputs are unavailable, when the switch is off, and
for the coach's request when no coach is on the panel.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import ideal_text_changes as itc
from services import judgement_follow_up as jf


class ServedRowTests(unittest.TestCase):
    def _run(self, rows):
        run = itc._ChangesRun.__new__(itc._ChangesRun)
        run.changes = rows
        run.arm_sid = "take-1"
        run.db = object()
        return run

    def test_served_moments_carry_the_card_and_notes_do_not(self):
        rows = [
            {"id": "m1", "source": "confident_voice", "snippet_id": "s1",
             "bookmark_tier": "weak"},
            {"id": "m2", "feedback_family": "confident_voice",
             "snippet_id": "s2", "bookmark_tier": "confident"},
            {"id": "m3", "source": "confident_voice", "snippet_id": "s3"},
            {"id": "n1", "feedback_family": "rewrite_clarity",
             "snippet_id": "s1"},
        ]
        run = self._run(rows)
        with patch.object(jf, "open_cards",
                          return_value={"s1": "coach_request", "s2": "praise"}
                          ) as called:
            run._open_cards()
        self.assertEqual(called.call_args.kwargs["snippet_ids"],
                         ["s1", "s2", "s3"])
        self.assertEqual(rows[0]["open_card"], "coach_request")
        self.assertEqual(rows[1]["open_card"], "praise")
        self.assertNotIn("open_card", rows[2])
        self.assertNotIn("open_card", rows[3])


if __name__ == "__main__":
    unittest.main()
