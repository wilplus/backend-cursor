"""The founder's ledger (build plan ML-2): counts about the machine, never
about a person; a source that fails is named, never read as zero; the
doors are read from the constants and cannot be changed here."""
from __future__ import annotations

import unittest
from unittest import mock

from services import learning_ledger as ll


class _Config:
    MLC2_TRAINING_SWITCH_ENABLED = False
    MLC2_PAIR_RELEASES_ENABLED = False
    MLC2_TRAINING_ENABLED = False
    MLC2_PROMOTION_ENABLED = False


class LedgerTests(unittest.TestCase):
    def setUp(self):
        # The coach-load row (Phase 2 addition, 2026-10-01) reads two tables
        # these stubs do not have; it is a source like the others.
        patcher = mock.patch("services.coach_load.coach_load", return_value={
            "since": "s", "moments_opened": 0,
            "requests": {"open": {}, "judgement": {}},
            "per_opened_moment": {"open": None, "judgement": None}})
        patcher.start()
        self.addCleanup(patcher.stop)
        after = mock.patch("services.bold_voices.after_practice_counts",
                           return_value={"since": "s", "practices_landed": 0})
        after.start()
        self.addCleanup(after.stop)
        for target, value in (("services.learning_ledger._peer_lane_counts", {"enabled": False}),
                              ("services.delayed_measure.report", {"enabled": False}),
                              # The coach panel's rows (0411): one source like
                              # the others, on or off, never read from these stubs.
                              ("services.learning_ledger._coach_panel_rows",
                               {"coach_preference": {}, "error_audit": {}, "detector_fair_test": {},
                                "block_pick": {}, "coach_word_pairs": {}})):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_every_jar_and_every_door_is_named(self):
        with mock.patch("services.feedback_pairs.counts", return_value={
                    "praise_line": {"total": 1, "unexported": 1},
                    "clearer_version": {"total": 0, "unexported": 0},
                    "exercise_script": {"total": 0, "unexported": 0}}), \
             mock.patch("services.exercise_learning_readiness.readiness",
                        return_value={"counted": 12, "bar": 300}), \
             mock.patch("services.verbal_cue_validation.report", return_value={
                    # Q24 A (2026-10-05): the coaches' Yes answers in the blind
                    # audit are the bar; the named moments are history only.
                    "hedging": {"audit_yes": 31, "caught_rate": 0.85, "audited": True,
                                "coach_named_measured": 0,
                                "clips_measured": 200, "false_alarm_rate": None},
                    "filler_cluster": {"audit_yes": 2, "caught_rate": None, "audited": True,
                                       "coach_named_measured": 40,
                                       "clips_measured": 200, "false_alarm_rate": None}}):
            out = ll.ledger(object(), config=_Config())
        self.assertEqual(out["ledger_version"], ll.LEDGER_VERSION)
        self.assertEqual(out["unavailable"], [])
        self.assertEqual(out["pairs"]["praise_line"]["run_bar"], ll.PAIRS_PER_RUN)
        self.assertFalse(out["pairs"]["praise_line"]["ready_for_run"])
        self.assertTrue(out["shadow_cues"]["hedging"]["ready"])
        self.assertEqual(out["shadow_cues"]["hedging"]["audit_yes_bar"], 30)
        self.assertFalse(out["shadow_cues"]["filler_cluster"]["ready"])
        self.assertIn("Yes answers", out["shadow_cues"]["filler_cluster"]["why_not"])
        self.assertEqual(out["shadow_cues"]["filler_cluster"]["named"], 40)
        self.assertEqual(set(out["doors"]), {"consent", "dataset_release", "training", "promotion"})
        self.assertFalse(any(d["open"] for d in out["doors"].values()))
        self.assertEqual(out["coach_load"]["moments_opened"], 0)

    def _with_exportable(self, exportable_unexported, *, down=False):
        exportable = mock.patch(
            "services.feedback_pairs.exportable",
            side_effect=RuntimeError("down") if down else None,
            return_value={"exercise_script": {"exportable": exportable_unexported,
                                              "exportable_unexported": exportable_unexported}})
        with mock.patch("services.feedback_pairs.counts", return_value={
                    "exercise_script": {"total": 400, "unexported": 400, "releasable": 300}}), \
             exportable, \
             mock.patch("services.exercise_learning_readiness.readiness", return_value={}), \
             mock.patch("services.verbal_cue_validation.report", return_value={}):
            return ll.ledger(object(), config=_Config())

    def test_only_pairs_the_export_can_release_fill_a_run_s_bar(self):
        """C9 (W6 2026-10-05): a run's bar of 200 counts the pairs the
        export contract can release, not every pair awaiting export. Both
        views ride the surface's row: W7's three counts and exposures, and
        the exportable ones."""
        entry = self._with_exportable(150)["pairs"]["exercise_script"]
        self.assertEqual((entry["unexported"], entry["releasable"]), (400, 300))
        self.assertEqual((entry["exportable"], entry["exportable_unexported"]), (150, 150))
        self.assertFalse(entry["ready_for_run"])
        self.assertTrue(self._with_exportable(200)["pairs"]["exercise_script"]["ready_for_run"])

    def test_an_unreadable_exportable_count_is_named_and_never_ready(self):
        out = self._with_exportable(500, down=True)
        self.assertIn("exportable_pairs", out["unavailable"])
        entry = out["pairs"]["exercise_script"]
        self.assertIsNone(entry["exportable"])
        self.assertIsNone(entry["exportable_unexported"])
        self.assertFalse(entry["ready_for_run"])

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
        # Doors 1 and 2 opened 2026-10-01 by the founder's sentences (door 2
        # for exercise_script only); doors 3 and 4 are shut.
        self.assertTrue(doors["consent"]["open"])
        self.assertTrue(doors["dataset_release"]["open"])
        # Door 2 for all three existing surfaces (N16, then C4 / N18).
        self.assertEqual(doors["dataset_release"]["surfaces"],
                         ["clearer_version", "exercise_script", "praise_line"])
        self.assertFalse(doors["training"]["open"])
        self.assertFalse(doors["promotion"]["open"])


if __name__ == "__main__":
    unittest.main()
