"""The learning-readiness count (step 8 prep; §3.5 item 8).

Pins:
  * only confirmed renders count, and only with a frozen trace whose signal
    rules are the ones in force today;
  * the targeted problems are the exercise's main targets for an exact fit
    and its secondary targets for a trial, and only those that fired;
  * only a speaker's first exposure per targeted problem enters the cohort;
  * below-minimum-probability draws are left out;
  * no attempt, or none valid, is missing data, not counted, and lowers the
    attempt rate; the LAST valid attempt is the endpoint, never the best;
  * the bar is 300 in all and 30 for every exercise in a ranked pool;
  * nothing about outcomes is ever computed or returned;
  * an unreadable source is named and blocks "ready";
  * the route sits behind the CMS password.
"""
from __future__ import annotations

import unittest

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


class CoachPickTests(unittest.TestCase):

    def test_a_coach_pick_is_never_in_the_ranked_pool(self):
        self.assertEqual(lr.ranked_pool(_coach_trace()), [])
