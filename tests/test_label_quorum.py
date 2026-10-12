"""The label ledger's four rules, enforced instead of documented
(services/label_quorum.py — founder 2026-08-11).

Each rule exists because a specific way of poisoning the ground-truth corpus
is easy to reach by accident. What each test class defends:

  RULE 1  A machine prediction that counts as a vote makes every later
          agreement number CIRCULAR — the model grading its own homework and
          reporting the result as human consensus. Unrecoverable after the
          fact, because nothing on the row says which votes were really the
          model's.
  RULE 2  A self-report counted as a peer means "two people agreed" can be
          one person agreeing with themselves. The speaker knows what they
          intended; that is the one judgment not independent of the thing
          judged.
  RULE 3  A singleton in the gold set is one opinion presented as truth; a
          singleton in the EVAL set is worse — the score is then measured
          against a coin flip and looks like a finding.
  RULE 4  "Not sure" is retained as rater uncertainty and routes a third
          person, but can never settle confidence ground truth. Audio unclear
          is a technical non-response and no confidence vote at all.

Pure, no DB. Run: python3 -m unittest tests.test_label_quorum
"""
from __future__ import annotations

import unittest

from services import label_quorum as lq


def _row(value=None, *, lane="game_peer", unrateable=False,
         self_report=False, state_id="confidence", rater="r"):
    return {
        "value": value, "lane": lane, "unrateable": unrateable,
        "self_report": self_report, "state_id": state_id, "rater_id": rater,
    }


class TestRule2OwnerIsNotAPeer(unittest.TestCase):
    """A self-report is calibration signal, never one of the two votes."""


    def test_blind_coach_and_blind_peer_share_one_human_quorum(self):
        # Provenance remains distinct on the rows, but both are independent
        # blind human judgments and therefore belong to the same panel.
        res = lq.resolve([
            _row("in_between", lane="coach", rater="coach-a"),
            _row("in_between", lane="game_peer", rater="peer-b"),
        ])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "in_between")
        self.assertEqual(res["n_responses"], 2)
        self.assertEqual(res["n_lane_excluded"], 0)


class TestRaterSubmissionAccess(unittest.TestCase):
    """Assignment remains fresh across an unclear-audio retry."""


    def test_fresh_rater_cannot_add_a_vote_after_resolution(self):
        rows = [_row("yes", rater="a"), _row("yes", rater="b")]
        access = lq.rater_submission_access(rows, "c")
        self.assertFalse(access["allowed"])
        self.assertEqual(access["outcome"], "closed")


if __name__ == "__main__":
    unittest.main()
