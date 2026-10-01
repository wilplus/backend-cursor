"""Two acoustic cues in the shadow stage (founder 2026-09-30, E10; ML-14).

Pins: the thresholds as the library definitions state them; a clip without
the readings logs nothing; the rows carry the detector version and no
language; the Take hook needs the practice yes and writes through the
shadow RPC; the drafted promotion names the acoustic detector.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import acoustic_cues as ac
from services import learning_weekly as lw


def _metrics(sep=20.0, f0_mean=120.0, f0_sd=12.0, frames=100):
    return {"noise_meter": {"version": "noise-meter-v1", "voice_db": -20.0,
                            "background_db": -20.0 - sep, "separation_db": sep},
            "f0_mean": f0_mean, "f0_sd": f0_sd, "pitch_frame_count": frames}


class MeasureTests(unittest.TestCase):
    def test_low_volume_fires_under_twelve_db_of_separation(self):
        self.assertFalse(ac.measure(_metrics(sep=20.0))["low_volume"]["fired"])
        self.assertTrue(ac.measure(_metrics(sep=8.0))["low_volume"]["fired"])

    def test_flat_pitch_fires_under_six_percent_variation_with_enough_frames(self):
        self.assertFalse(ac.measure(_metrics(f0_sd=12.0))["flat_pitch"]["fired"])
        self.assertTrue(ac.measure(_metrics(f0_sd=4.0))["flat_pitch"]["fired"])
        self.assertNotIn("flat_pitch", ac.measure(_metrics(f0_sd=4.0, frames=10)))

    def test_a_clip_without_readings_logs_nothing(self):
        self.assertIsNone(ac.measure({}))
        self.assertIsNone(ac.measure(None))
        only_pitch = ac.measure({"f0_mean": 100.0, "f0_sd": 1.0, "pitch_frame_count": 40})
        self.assertEqual(list(only_pitch), ["flat_pitch"])

    def test_rows_carry_the_version_and_no_language(self):
        rows = ac.take_observations([{"id": "s1", "recording_id": "r1", "metrics": _metrics(sep=5.0)},
                                     {"id": "s2", "metrics": None}], take_session_id="t1")
        self.assertEqual({r["error_id"] for r in rows}, {"low_volume", "flat_pitch"})
        self.assertTrue(all(r["detector_version"] == ac.ACOUSTIC_CUES_VERSION for r in rows))
        self.assertTrue(all(r["language"] == "any" for r in rows))
        self.assertTrue(next(r for r in rows if r["error_id"] == "low_volume")["fired"])


class TakeHookTests(unittest.TestCase):
    def test_record_take_needs_the_practice_yes_and_writes_through_the_rpc(self):
        db = mock.Mock()
        db.get_snippets_by_session.return_value = [{"id": "s1", "metrics": _metrics()}]
        db.record_verbal_cue_shadow.return_value = 2
        with mock.patch("services.verbal_cues._practice_permitted", return_value=False):
            self.assertEqual(ac.record_take(db, "t1"), 0)
        db.record_verbal_cue_shadow.assert_not_called()
        with mock.patch("services.verbal_cues._practice_permitted", return_value=True):
            self.assertEqual(ac.record_take(db, "t1"), 2)
        rows = db.record_verbal_cue_shadow.call_args.args[0]
        self.assertEqual(len(rows), 2)

    def test_the_drafted_promotion_names_the_acoustic_detector(self):
        self.assertIn("detector_ref = 'acoustic_cues:flat_pitch'", lw.migration_draft("flat_pitch")["sql"])
        self.assertIn("detector_ref = 'verbal_cues:hedging'", lw.migration_draft("hedging")["sql"])

    def test_the_library_migration_seeds_both_as_shadow(self):
        import pathlib
        sql = (pathlib.Path(__file__).resolve().parents[1]
               / "migrations" / "a_model_learns_only_from_the_yes.sql").read_text()
        for cue in ac.CUES:
            self.assertIn(f"'acoustic_cues:{cue}'", sql)
        self.assertNotIn("'detected',\n    'acoustic_cues", sql)


if __name__ == "__main__":
    unittest.main()
