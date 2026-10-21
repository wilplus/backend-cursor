"""
STORY    As a coach, I want my rating stored exactly as I gave it, blind by
         default, so that the training data holds only real, independent
         human judgements.
OUTCOME
  O1  Never-2: a rating is stored as given and marked blind unless the route
      says the rater saw the machine's read.
  O2  A wrong-typed value (a truthy string, a bool) is refused, never coerced.
  O3  A state with no written definition cannot be rated.
  O4  The lane comes from the rating act's provenance: an unverified coach
      act is bootstrap, never panel.
  O5  Aggregation leaves out bootstrap rows, a self-report in any lane and an
      answer given after seeing the other side, and counts "audio unclear" apart.
  O6  A five-rater panel at 60% outweighs a unanimous pair.
PROVES   O1 -> test_blind_is_the_default_and_the_answer_is_kept
         O2 -> test_truthy_strings_are_refused_not_coerced
         O3 -> test_a_state_without_a_definition_is_refused
         O4 -> test_lane_comes_from_provenance
         O5 -> test_bootstrap_and_unclear_rows_stay_out_of_the_label
         O6 -> test_panel_size_outweighs_agreement
"""
from __future__ import annotations

import unittest

from services.state_ratings import (
    aggregate,
    quality,
    resolve_lane,
    validate_rating,
)


class RatingIntakeTests(unittest.TestCase):
    def test_blind_is_the_default_and_the_answer_is_kept(self):
        row, err = validate_rating({"state_id": "confidence",
                                    "value": "in_between"})
        self.assertIsNone(err)
        self.assertEqual(row["value"], "in_between")
        self.assertIs(row["saw_model_output"], False)
        # Only the route can say the rater saw the machine's read.
        row, _ = validate_rating({"state_id": "confidence", "value": "yes",
                                  "saw_model_output": True})
        self.assertIs(row["saw_model_output"], False)
        row, _ = validate_rating({"state_id": "confidence", "value": "yes"},
                                 saw_model_output=True)
        self.assertIs(row["saw_model_output"], True)

    def test_truthy_strings_are_refused_not_coerced(self):
        for payload in ({"state_id": "confidence", "value": True},
                        {"state_id": "confidence", "value": "Yes"},
                        {"state_id": "confidence", "value": "true"},
                        {"state_id": "confidence", "value": "yes",
                         "unrateable": "true"}):
            row, err = validate_rating(payload)
            self.assertIsNone(row, payload)
            self.assertTrue(err)

    def test_a_state_without_a_definition_is_refused(self):
        row, err = validate_rating({"state_id": "charisma", "value": "yes"})
        self.assertIsNone(row)
        self.assertIn("operational definition", err)


class LaneAndAggregationTests(unittest.TestCase):
    def test_lane_comes_from_provenance(self):
        self.assertEqual(resolve_lane(is_coach=True), "bootstrap")
        self.assertEqual(resolve_lane(is_coach=True, panel_grade=True), "coach")
        self.assertEqual(resolve_lane(is_coach=False), "game_peer")
        self.assertEqual(resolve_lane(is_coach=False, is_owner=True),
                         "game_owner")

    def test_bootstrap_and_unclear_rows_stay_out_of_the_label(self):
        label = aggregate([
            {"lane": "coach", "value": "yes"},
            {"lane": "game_peer", "value": "yes"},
            {"lane": "coach", "value": "audio_unclear"},
            {"lane": "bootstrap", "value": "no"},
            {"lane": "bootstrap", "value": "no"},
            {"lane": "game_owner", "value": "no"},
            {"lane": "coach", "value": "no", "self_report": True},
            {"lane": "coach", "value": "no", "blind": False},
        ])
        self.assertEqual(label["n_raters"], 2)
        self.assertEqual(label["by_value"], {"yes": 2, "in_between": 0, "no": 0})
        self.assertEqual(label["unrateable_n"], 1)
        self.assertIsNone(aggregate([{"lane": "bootstrap", "value": "yes"}]))

    def test_panel_size_outweighs_agreement(self):
        self.assertGreater(quality(5, 0.6), quality(2, 1.0))


if __name__ == "__main__":
    unittest.main()
