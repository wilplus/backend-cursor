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

import json
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


class TargetTests(unittest.TestCase):
    def test_an_exact_fit_is_judged_on_its_main_targets_that_fired(self):
        trace = _trace(observed=("rushing", "mumbling"),
                       main=("rushing", "ending"), secondary=("mumbling",))
        self.assertEqual(lr.targeted_problems(trace, "room"), {"rushing"})

    def test_a_trial_is_judged_on_its_secondary_targets(self):
        trace = _trace(fit="trial", observed=("rushing", "mumbling"),
                       main=("ending",), secondary=("mumbling",))
        self.assertEqual(lr.targeted_problems(trace, "room"), {"mumbling"})

    def test_the_pool_is_the_ranked_candidates_only(self):
        self.assertEqual(lr.ranked_pool(_trace()), ["room", "slow"])


class EndpointTests(unittest.TestCase):
    def test_the_last_valid_attempt_is_the_endpoint(self):
        tries = [_attempt(1), _attempt(2), _attempt(3, valid=False)]
        self.assertEqual(lr.endpoint_attempt(tries)["attempt_index"], 2)

    def test_only_the_first_three_attempts_count(self):
        tries = [_attempt(1, valid=False), _attempt(2, valid=False),
                 _attempt(3, valid=False), _attempt(4)]
        self.assertIsNone(lr.endpoint_attempt(tries))

    def test_an_attempt_needs_alignment_audio_and_a_confidence_read(self):
        self.assertTrue(lr.attempt_is_valid(_attempt(1)))
        for broken in ({"aligned_words": 2}, {"confidence": None},
                       {"voiced_ratio": 0.1}, {"confidence": True}):
            attempt = _attempt(1)
            attempt["acoustic_metrics"].update(broken)
            self.assertFalse(lr.attempt_is_valid(attempt), broken)
        self.assertFalse(lr.attempt_is_valid(_attempt(1, valid=False)))


class CountTests(unittest.TestCase):
    def test_a_first_exposure_with_a_valid_attempt_counts(self):
        out = _World().add().build()
        self.assertEqual((out["exposures"], out["cohort"], out["counted"]),
                         (1, 1, 1))
        self.assertEqual(out["attempt_rate"], 1.0)
        self.assertEqual(out["counted_by_selection_mode"], {"top": 1})

    def test_each_exclusion_is_named(self):
        world = (_World()
                 .add(owner="a", traced=False)
                 .add(owner="b", trace=_trace(observed=("mumbling",)))
                 .add(owner="c", trace=_trace(rules="cv-exercise-signals-v0"))
                 .add(owner="d").add(owner="d")
                 .add(owner="e", below=True)
                 .add(owner="f", attempts=0)
                 .add(owner="g", valid=False))
        out = world.build()
        self.assertEqual(out["excluded"], {
            "untraced": 1, "no_targeted_problem": 1, "rules_changed": 1,
            "repeat": 1, "below_minimum_probability": 1, "no_attempt": 1,
            "no_valid_attempt": 1})
        self.assertEqual(out["counted"], 1)          # d's first
        self.assertEqual(out["cohort"], 3)           # d's first, f, g
        self.assertEqual(out["attempt_rate"], round(1 / 3, 4))

    def test_a_repeat_is_by_targeted_problem_per_speaker(self):
        other = _trace(observed=("mumbling",), main=("mumbling",))
        out = (_World().add(owner="u").add(owner="u", trace=other)
               .add(owner="v").build())
        self.assertEqual((out["counted"], out["excluded"]["repeat"]), (3, 0))
        out = _World().add(owner="u").add(owner="u").build()
        self.assertEqual((out["counted"], out["excluded"]["repeat"]), (1, 1))

    def test_first_means_earliest_render_not_list_order(self):
        world = _World().add(owner="u", at="2026-09-28T12:00",
                             attempts=0).add(owner="u", at="2026-09-28T09:00")
        out = world.build()
        self.assertEqual((out["counted"], out["excluded"]["repeat"]), (1, 1))

    def test_the_bar_is_300_and_30_per_ranked_exercise(self):
        world = _World()
        for i in range(300):
            world.add(owner=f"s{i}")
        out = world.build()
        self.assertEqual(out["counted"], 300)
        self.assertFalse(out["ready"])               # "slow" was ranked, 0 tries
        self.assertIn("slow", out["why_not"])
        rows = {r["exercise_id"]: r for r in out["exercises"]}
        self.assertEqual(rows["slow"]["counted"], 0)
        self.assertNotIn("unfit", rows)              # excluded, never ranked
        for i in range(30):
            world.add(owner=f"t{i}", exercise="slow")
        self.assertTrue(world.build()["ready"])

    def test_below_the_total_says_how_far(self):
        out = _World().add().build()
        self.assertFalse(out["ready"])
        self.assertTrue(out["why_not"].startswith("1 of 300"))

    def test_nothing_about_outcomes_is_returned(self):
        text = json.dumps(_World().add().build()).lower()
        for word in ("helped", "success", "improved", "fired_on_endpoint",
                     "confidence"):
            self.assertNotIn(word, text)

    def test_the_contract_is_named(self):
        out = _World().build()
        self.assertEqual(out["label_spec_version"], "exercise-adequacy-label-v1")
        self.assertEqual(out["bar"], {"min_counted": 300,
                                      "min_per_exercise": 30})
        self.assertIsNone(out["attempt_rate"])


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


class ReadTests(unittest.TestCase):
    def test_it_reads_every_source(self):
        db = _Db()
        out = lr.readiness(db)
        self.assertEqual(out["unavailable"], [])
        self.assertEqual(out["counted"], 1)
        self.assertEqual(db.practice_ids, ["p1"])

    def test_an_unreadable_source_is_named_and_never_ready(self):
        out = lr.readiness(_Db(fail={"match_traces"}))
        self.assertEqual(out["unavailable"], ["match_traces"])
        self.assertFalse(out["ready"])
        self.assertIn("match_traces", out["why_not"])


class _Query:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self.log.append((start, end))
        self.window = (start, end)
        return self

    def execute(self):
        start, end = self.window
        return type("R", (), {"data": self.rows[start:end + 1]})()


class PagingTests(unittest.TestCase):
    def test_exposures_are_read_past_the_server_row_cap(self):
        from services.db import DatabaseService
        rows = [{"assignment_id": f"a{i}"} for i in range(2500)]
        log: list = []
        fake = DatabaseService.__new__(DatabaseService)
        fake.client = type("C", (), {"table": lambda self, _n: _Query(rows, log)})()
        self.assertEqual(len(fake.list_exercise_exposures()), 2500)
        self.assertEqual(log, [(0, 999), (1000, 1999), (2000, 2999)])


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
    def test_a_coach_pick_is_judged_on_every_target_it_claims_that_fired(self):
        targets = lr.targeted_problems(_coach_trace(), "coach-pick")
        self.assertEqual(targets, frozenset({"rushing", "ending_compression"}))
        self.assertEqual(
            lr.targeted_problems(_coach_trace(observed=("mumbling",)),
                                 "coach-pick"),
            frozenset())

    def test_a_coach_pick_is_never_in_the_ranked_pool(self):
        self.assertEqual(lr.ranked_pool(_coach_trace()), [])

    def test_a_coach_pick_counts_under_its_own_mode(self):
        out = (_World()
               .add(exercise="coach-pick", owner="o1", mode="coach_chosen",
                    trace=_coach_trace(), attempts=1)
               .add(exercise="room", owner="o2", mode="top", attempts=1)
               .build())
        self.assertEqual(out["counted"], 2)
        self.assertEqual(out["counted_by_selection_mode"],
                         {"coach_chosen": 1, "top": 1})
        by_id = {row["exercise_id"]: row for row in out["exercises"]}
        self.assertEqual(by_id["coach-pick"]["counted"], 1)
        # The bar's per-exercise pool is the ranked exercises only: the
        # machine draw's pool is listed, the coach pick adds nothing to it.
        listed = {row["exercise_id"] for row in out["exercises"]}
        self.assertEqual(listed, {"coach-pick", "room", "slow"})
        self.assertIn("2 of 300", out["why_not"])

    def test_a_coach_pick_seen_first_makes_the_machine_pick_a_repeat(self):
        out = (_World()
               .add(exercise="coach-pick", owner="o1", mode="coach_chosen",
                    trace=_coach_trace(observed=("rushing",), main=("rushing",),
                                       secondary=()), attempts=1)
               .add(exercise="room", owner="o1", mode="top", attempts=1)
               .build())
        self.assertEqual(out["counted"], 1)
        self.assertEqual(out["excluded"]["repeat"], 1)
