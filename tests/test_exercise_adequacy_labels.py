"""The scorekeeper (step 8 prep; §3.5 item 1).

Pins:
  * helped means none of the targeted problems fires on the endpoint attempt;
    a problem the exercise did not target never decides it;
  * the endpoint is measured by the original clip's own rules
    (`clip_signals`) and the vocabulary frozen in the trace;
  * the endpoint is the LAST valid attempt, even when an earlier one was
    better;
  * only exposures the counter counts are labelled — the same cohort;
  * the labels stay sealed until the evidence bar is met, and a sealed answer
    carries nothing but the reason;
  * nothing a person said or judged is read (item 10).
"""
from __future__ import annotations

import inspect
import unittest

from services import confident_voice_practice as cvp
from services import exercise_adequacy_labels as sk
from tests.test_exercise_learning_readiness import RULES, _Db, _trace, _World

# pause_ratio < 0.08 fires insufficient_pauses → "rushing".
RUSHING = {"pause_ratio": 0.02}
CALM = {"pause_ratio": 0.2}
# ending_duration_ratio < 0.78 fires compressed_ending → "ending_compression".
ENDING = {"ending_duration_ratio": 0.5}


def _with_endpoint(world, *snaps):
    """Replace the last exposure's attempts with valid ones carrying `snaps`."""
    practice = f"p{len(world.exposures)}"
    world.attempts[practice] = [
        {"attempt_index": i, "duration_ms": 4000, "audio_ref": "s3://x",
         "acoustic_metrics": {"aligned_words": 9, "confidence": 0.3,
                              "voiced_ratio": 0.6, **snap}}
        for i, snap in enumerate(snaps, start=1)]
    return world


class EndpointTests(unittest.TestCase):
    def test_the_original_clip_s_own_rules_measure_the_attempt(self):
        attempt = {"acoustic_metrics": {**RUSHING, **ENDING}}
        self.assertEqual(sk.endpoint_problems(attempt, _trace()),
                         {"rushing", "ending_compression"})

    def test_the_frozen_vocabulary_filters_the_attempt(self):
        trace = {**_trace(), "vocabulary": ["rushing"]}
        attempt = {"acoustic_metrics": {**RUSHING, **ENDING}}
        self.assertEqual(sk.endpoint_problems(attempt, trace), {"rushing"})

    def test_the_rules_are_the_eligibility_rules(self):
        self.assertIn("clip_signals(snap)",
                      inspect.getsource(cvp.exercise_eligibility))


class LabelTests(unittest.TestCase):
    def _labels(self, world):
        return sk.build_labels(
            signal_rules_version=RULES, exposures=world.exposures,
            assignments=world.assignments, traces=world.traces,
            practices=world.practices, attempts=world.attempts)

    def test_helped_when_the_targeted_problem_is_gone(self):
        [row] = self._labels(_with_endpoint(_World().add(), CALM))
        self.assertTrue(row["helped"])
        self.assertEqual((row["targeted_problems"], row["still_firing"]),
                         (["rushing"], []))
        self.assertEqual(row["label_spec_version"], "exercise-adequacy-label-v1")

    def test_not_helped_when_it_still_fires(self):
        [row] = self._labels(_with_endpoint(_World().add(), RUSHING))
        self.assertFalse(row["helped"])
        self.assertEqual(row["still_firing"], ["rushing"])

    def test_an_untargeted_problem_never_decides_it(self):
        [row] = self._labels(_with_endpoint(_World().add(), {**CALM, **ENDING}))
        self.assertTrue(row["helped"])

    def test_the_last_valid_attempt_decides_not_the_best(self):
        [row] = self._labels(_with_endpoint(_World().add(), CALM, RUSHING))
        self.assertFalse(row["helped"])
        self.assertEqual(row["endpoint_attempt_index"], 2)

    def test_a_trial_is_judged_on_its_secondary_target(self):
        trace = _trace(fit="trial", observed=("rushing",), main=("ending",),
                       secondary=("rushing",))
        [row] = self._labels(_with_endpoint(_World().add(trace=trace), CALM))
        self.assertEqual((row["fit"], row["targeted_problems"], row["helped"]),
                         ("trial", ["rushing"], True))

    def test_only_what_the_counter_counts_is_labelled(self):
        world = (_World().add(owner="a").add(owner="a")      # repeat
                 .add(owner="b", attempts=0)                  # no attempt
                 .add(owner="c", below=True)                  # low odds
                 .add(owner="d", traced=False))               # untraced
        rows = self._labels(world)
        self.assertEqual([r["owner_user_id"] for r in rows], ["a"])

    def test_nothing_a_person_said_or_judged_is_read(self):
        source = inspect.getsource(sk)
        for field in ("user_answer", "coach_decision", "professional_coach",
                      "peer", "shadow_observations"):
            self.assertNotIn(field, source.split('"""', 2)[2], field)


class SealTests(unittest.TestCase):
    def test_sealed_until_the_bar_is_met(self):
        out = sk.labels(_Db())
        self.assertEqual(set(out), {"sealed", "why_not", "label_spec_version"})
        self.assertTrue(out["sealed"])
        self.assertTrue(out["why_not"].startswith("1 of 300"))

    def test_unsealed_once_ready(self):
        db = _Db()
        db.world = _World()
        for i in range(300):
            db.world.add(owner=f"s{i}")
        for i in range(30):
            db.world.add(owner=f"t{i}", exercise="slow")
        out = sk.labels(db)
        self.assertFalse(out["sealed"])
        self.assertEqual(len(out["labels"]), 330)

    def test_an_unreadable_source_keeps_it_sealed(self):
        out = sk.labels(_Db(fail={"attempts"}))
        self.assertTrue(out["sealed"])
        self.assertIn("attempts", out["why_not"])

    def test_no_route_serves_the_labels(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in (root / "routes").rglob("*.py"):
            self.assertNotIn("exercise_adequacy_labels", path.read_text(),
                             str(path))
