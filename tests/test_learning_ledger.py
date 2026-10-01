"""The founder's ledger (build plan ML-2): counts about the machine, never
about a person; a source that fails is named, never read as zero; the
doors are read from the constants and cannot be changed here."""
from __future__ import annotations

import unittest
from unittest import mock

from services import learning_ledger as ll


class _Config:
    MLC2_TRAINING_SWITCH_ENABLED = False
    MLC2_DATASET_RELEASES_ENABLED = False
    MLC2_TRAINING_ENABLED = False
    MLC2_PROMOTION_ENABLED = False


class LedgerTests(unittest.TestCase):
    def test_every_jar_and_every_door_is_named(self):
        with mock.patch("services.feedback_pairs.counts", return_value={
                    "praise_line": {"total": 1, "unexported": 1},
                    "clearer_version": {"total": 0, "unexported": 0},
                    "exercise_script": {"total": 0, "unexported": 0}}), \
             mock.patch("services.exercise_learning_readiness.readiness",
                        return_value={"counted": 12, "bar": 300}), \
             mock.patch("services.verbal_cue_validation.report", return_value={
                    "hedging": {"coach_named_measured": 31, "caught_rate": 0.85,
                                "clips_measured": 200, "false_alarm_rate": None},
                    "filler_cluster": {"coach_named_measured": 2, "caught_rate": None,
                                       "clips_measured": 200, "false_alarm_rate": None}}):
            out = ll.ledger(object(), config=_Config())
        self.assertEqual(out["ledger_version"], ll.LEDGER_VERSION)
        self.assertEqual(out["unavailable"], [])
        self.assertEqual(out["pairs"]["praise_line"]["run_bar"], ll.PAIRS_PER_RUN)
        self.assertFalse(out["pairs"]["praise_line"]["ready_for_run"])
        self.assertTrue(out["shadow_cues"]["hedging"]["ready"])
        self.assertFalse(out["shadow_cues"]["filler_cluster"]["ready"])
        self.assertEqual(set(out["doors"]), {"consent", "dataset_release", "training", "promotion"})
        self.assertFalse(any(d["open"] for d in out["doors"].values()))

    def test_a_source_that_fails_is_named_not_zeroed(self):
        with mock.patch("services.feedback_pairs.counts", side_effect=RuntimeError("down")), \
             mock.patch("services.exercise_learning_readiness.readiness", return_value={}), \
             mock.patch("services.verbal_cue_validation.report", return_value={}):
            out = ll.ledger(object(), config=_Config())
        self.assertEqual(out["unavailable"], ["pairs"])
        self.assertEqual(out["pairs"], {})

    def test_the_doors_are_the_code_constants(self):
        from config import Config
        doors = ll.doors(Config())
        # Door 1 opened 2026-10-01 by the founder's sentence; the rest are shut.
        self.assertTrue(doors["consent"]["open"])
        self.assertFalse(doors["training"]["open"])
        self.assertFalse(doors["dataset_release"]["open"])
        self.assertFalse(doors["promotion"]["open"])


if __name__ == "__main__":
    unittest.main()
