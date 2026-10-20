"""
STORY    As the founder, I want the learning-readiness count to include only
         real, comparable first exposures and never compute outcomes, so that
         "ready to learn" means enough clean data.
OUTCOME
  O1  A render with no frozen trace, or one traced under other signal rules,
      is not counted; nothing about outcomes is computed or returned.
  O2  Only a speaker's first exposure per targeted problem counts; a repeat
      is counted as a repeat.
  O3  The endpoint is the FIRST valid attempt (F7, founder 2026-10-01); no
      attempt is missing data that lowers the attempt rate, never a zero.
  O4  The bar is 300 in all and 30 for every exercise in a ranked pool.
  O5  An unreadable source is named and blocks "ready".
  O6  A coach's pick is never in the ranked pool.
PROVES   O1 -> test_untraced_or_old_rules_renders_are_not_counted
         O2 -> test_only_the_first_exposure_per_problem_counts
         O3 -> test_the_first_valid_attempt_is_the_endpoint_and_none_is_missing_data
         O4 -> test_the_bar_is_300_in_all_and_30_per_ranked_exercise
         O5 -> test_an_unreadable_source_blocks_ready
         O6 -> test_a_coach_pick_is_never_in_the_ranked_pool
WHY      docs/history/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5 (items 1-8).
"""
from __future__ import annotations

import unittest

import json

from services import exercise_learning_readiness as lr

RULES = "cv-exercise-signals-v1"


def _trace(fit="exact", observed=("rushing",), selected="room",
           main=("rushing",), secondary=(), pool=("room", "slow"),
           rules=RULES):
    candidates = [{"exercise_id": selected, "outcome": "ranked",
                   "main_targets": list(main),
                   "secondary_targets": list(secondary)}]
    candidates += [{"exercise_id": e, "outcome": "ranked",
                    "main_targets": ["rushing"], "secondary_targets": []}
                   for e in pool if e != selected]
    candidates.append({"exercise_id": "unfit", "outcome": "excluded",
                       "main_targets": ["mumbling"], "secondary_targets": []})
    return {"fit": fit, "observed_tags": list(observed),
            "candidates": candidates, "signal_rules_version": rules}


def _attempt(index, *, valid=True):
    return {"attempt_index": index, "duration_ms": 4000 if valid else 500,
            "audio_ref": "s3://x", "acoustic_metrics": {
                "aligned_words": 9, "confidence": 0.3, "voiced_ratio": 0.6}}


class _World:
    """One exposure per call to add(); builds the four maps."""

    def __init__(self):
        self.exposures, self.assignments, self.traces = [], {}, {}
        self.practices, self.attempts = {}, {}

    def add(self, *, owner="u1", exercise="room", trace=None, attempts=1,
            valid=True, mode="top", below=False, at=None, traced=True):
        n = len(self.exposures) + 1
        asg = f"a{n}"
        self.exposures.append({"assignment_id": asg, "owner_user_id": owner,
                               "exercise_id": exercise,
                               "rendered_at": at or f"2026-09-28T10:{n:02d}"})
        self.assignments[asg] = {"selection_mode": mode,
                                 "below_minimum_probability": below}
        if traced:
            self.traces[asg] = trace or _trace(selected=exercise)
        if attempts:
            self.practices[asg] = {"id": f"p{n}"}
            self.attempts[f"p{n}"] = [_attempt(i, valid=valid)
                                      for i in range(1, attempts + 1)]
        return self

    def build(self, rules=RULES):
        return lr.build_readiness(
            exposures=self.exposures, assignments=self.assignments,
            traces=self.traces, practices=self.practices,
            attempts=self.attempts, signal_rules_version=rules)


class _Db:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.world = _World().add()

    def _maybe(self, name, value):
        if name in self.fail:
            raise RuntimeError("relation does not exist")
        return value

    def list_exercise_exposures(self):
        return self._maybe("exposures", self.world.exposures)

    def get_exercise_assignments(self, ids):
        return self._maybe("assignments", self.world.assignments)

    def get_exercise_match_traces(self, ids):
        return self._maybe("match_traces", self.world.traces)

    def get_practices_for_assignments(self, ids):
        return self._maybe("practices", self.world.practices)

    def list_attempts_for_practices(self, ids):
        self.practice_ids = ids
        return self._maybe("attempts", self.world.attempts)


# ── A COACH'S PICK COUNTS, FLAGGED (founder 2026-09-29, decision 3; 0398) ─


def _coach_trace(observed=("rushing", "ending_compression"),
                 main=("rushing",), secondary=("ending_compression",),
                 rules=RULES):
    return {"fit": None, "observed_tags": list(observed),
            "candidates": [{"exercise_id": "coach-pick",
                            "outcome": "coach_chosen",
                            "main_targets": list(main),
                            "secondary_targets": list(secondary)}],
            "signal_rules_version": rules}


class ReadinessTests(unittest.TestCase):

    def test_untraced_or_old_rules_renders_are_not_counted(self):
        world = (_World().add(owner="u1", traced=False)
                 .add(owner="u2", trace=_trace(rules="cv-exercise-signals-v0"))
                 .add(owner="u3"))
        out = world.build()
        self.assertEqual(out["counted"], 1)
        self.assertEqual(out["excluded"]["untraced"], 1)
        self.assertEqual(out["excluded"]["rules_changed"], 1)
        self.assertNotIn("helped", json.dumps(out))

    def test_only_the_first_exposure_per_problem_counts(self):
        out = (_World().add(owner="u1").add(owner="u1", exercise="slow")
               .add(owner="u2")).build()
        self.assertEqual(out["counted"], 2)
        self.assertEqual(out["excluded"]["repeat"], 1)

    def test_the_first_valid_attempt_is_the_endpoint_and_none_is_missing_data(self):
        world = _World().add(owner="u1").add(owner="u2", attempts=0)
        world.attempts["p1"] = [_attempt(3), _attempt(1, valid=False), _attempt(2)]
        records = lr.cohort_records(
            exposures=world.exposures, assignments=world.assignments,
            traces=world.traces, practices=world.practices,
            attempts=world.attempts, signal_rules_version=RULES)
        self.assertEqual(records[0]["endpoint"]["attempt_index"], 2)
        self.assertEqual(records[1]["excluded"], "no_attempt")
        out = world.build()
        self.assertEqual((out["cohort"], out["counted"]), (2, 1))
        self.assertEqual(out["attempt_rate"], 0.5)

    def test_the_bar_is_300_in_all_and_30_per_ranked_exercise(self):
        def world(n, pool):
            w = _World()
            for i in range(n):
                w.add(owner=f"u{i}", trace=_trace(pool=pool))
            return w.build()

        ready = world(300, ("room",))
        self.assertTrue(ready["ready"])
        self.assertIsNone(ready["why_not"])
        short = world(299, ("room",))
        self.assertFalse(short["ready"])
        self.assertEqual(short["why_not"],
                         "299 of 300 first-exposure attempts with a valid endpoint")
        thin = world(300, ("room", "slow"))
        self.assertFalse(thin["ready"])
        self.assertEqual(thin["why_not"], "1 exercise(s) below 30: slow")

    def test_an_unreadable_source_blocks_ready(self):
        out = lr.readiness(_Db(fail=("match_traces",)))
        self.assertFalse(out["ready"])
        self.assertEqual(out["unavailable"], ["match_traces"])
        self.assertEqual(out["why_not"], "unreadable: match_traces")


class CoachPickTests(unittest.TestCase):

    def test_a_coach_pick_is_never_in_the_ranked_pool(self):
        self.assertEqual(lr.ranked_pool(_coach_trace()), [])
