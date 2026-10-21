"""
STORY    As the founder, I want ground-truth labels settled only by
         independent blind humans, so that our confidence data is never
         circular.
OUTCOME
  O1  A machine prediction never counts as a vote: a machine-lane row, or a
      machine value beside a human answer, adds nothing.
  O2  Never-2 (coach judgements stay blind): a rating made after the rater
      saw the clip's non-blind side is not a vote.
  O3  A self-report (the speaker's own answer) is never one of the votes.
  O4  One rating never settles; only two matching blind humans do, and a
      blind coach and a blind peer share one quorum.
  O5  Not sure and Audio unclear never settle a label.
  O6  Once settled, no further vote is accepted.
  O7  Two historical v1 "neutral" answers keep J6's meaning: the clip is
      closed (perceptually ambiguous), never routed again, never a label.
      One neutral is still an IDK, and a perceptual quorum still wins.
PROVES   O1 -> test_a_machine_prediction_is_never_a_vote
         O2 -> test_a_rating_that_was_not_blind_is_not_a_vote
         O3 -> test_a_self_report_is_never_a_vote
         O4 -> test_a_singleton_never_settles,
               test_blind_coach_and_blind_peer_share_one_human_quorum
         O5 -> test_not_sure_and_audio_unclear_never_settle
         O6 -> test_fresh_rater_cannot_add_a_vote_after_resolution
         O7 -> test_two_v1_neutrals_stay_closed_but_are_never_a_label
WHY      Founder 2026-08-11: a model grading its own homework, or one person
         agreeing with themselves, poisons the gold set beyond repair.
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


class TestWhoseVoteCounts(unittest.TestCase):

    def test_a_machine_prediction_is_never_a_vote(self):
        res = lq.resolve([
            {**_row("yes", rater="human-a"), "machine_value": "yes"},
            _row("yes", lane="machine", rater="model-v3"),
        ])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertIsNone(res["value"])
        self.assertEqual(res["machine_votes"], 0)
        self.assertEqual(res["n_lane_excluded"], 1)

    def test_a_rating_that_was_not_blind_is_not_a_vote(self):
        res = lq.resolve([
            _row("no", lane="coach", rater="coach-a"),
            {**_row("no", lane="coach", rater="coach-b"), "blind": False},
        ])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertFalse(res["settled"])
        # Blind, the same two answers settle.
        self.assertEqual(lq.resolve([
            _row("no", lane="coach", rater="coach-a"),
            {**_row("no", lane="coach", rater="coach-b"), "blind": True},
        ])["value"], "no")

    def test_a_self_report_is_never_a_vote(self):
        for own in (_row("yes", self_report=True, lane="coach", rater="o"),
                    # a row written before the flag existed: the lane says it
                    {k: v for k, v in _row("yes", lane="game_owner",
                                           rater="o").items()
                     if k != "self_report"}):
            with self.subTest(own=own["lane"]):
                res = lq.resolve([own, _row("yes", rater="peer-b")])
                self.assertEqual(res["status"], lq.SINGLETON)
                self.assertEqual(res["n_self_report"], 1)

    def test_a_singleton_never_settles(self):
        res = lq.resolve([_row("yes", lane="coach", rater="coach-a")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertFalse(res["gold_eligible"] or res["eval_eligible"])
        self.assertIsNone(res["value"])

    def test_not_sure_and_audio_unclear_never_settle(self):
        for rows in ([_row("not_sure", rater="a"), _row("not_sure", rater="b")],
                     [_row("yes", rater="a"), _row("not_sure", rater="b")],
                     [_row("audio_unclear", rater="a"),
                      _row("audio_unclear", rater="b")],
                     [_row(None, unrateable=True, rater="a"),
                      _row("yes", rater="b")]):
            with self.subTest(rows=[r["value"] for r in rows]):
                res = lq.resolve(rows)
                self.assertFalse(res["settled"], res["status"])
                self.assertIsNone(res["value"])

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


    def test_two_v1_neutrals_stay_closed_but_are_never_a_label(self):
        res = lq.resolve([_row("neutral", rater="a"), _row("neutral", rater="b")])
        self.assertEqual(res["status"], lq.PERCEPTUALLY_AMBIGUOUS)
        self.assertIsNone(res["value"])
        self.assertFalse(res["settled"])
        self.assertFalse(res["gold_eligible"])
        self.assertFalse(res["needs_rater"])
        self.assertEqual(lq.routing_priority(res), lq.P_SETTLED)
        self.assertEqual(
            lq.rater_submission_access([_row("neutral", rater="a"), _row("neutral", rater="b")],
                                       "c")["outcome"], "closed")
        self.assertEqual(
            lq.resolve([_row("neutral", rater="a"), _row("not_sure", rater="b")])["status"],
            lq.NEEDS_THIRD)
        won = lq.resolve([_row("neutral", rater="a"), _row("neutral", rater="b"),
                          _row("yes", rater="c"), _row("yes", rater="d")])
        self.assertEqual((won["status"], won["value"]), (lq.QUORUM, "yes"))


class TestRaterSubmissionAccess(unittest.TestCase):
    """Assignment remains fresh across an unclear-audio retry."""


    def test_fresh_rater_cannot_add_a_vote_after_resolution(self):
        rows = [_row("yes", rater="a"), _row("yes", rater="b")]
        access = lq.rater_submission_access(rows, "c")
        self.assertFalse(access["allowed"])
        self.assertEqual(access["outcome"], "closed")


if __name__ == "__main__":
    unittest.main()
