"""willab — Measured delivery stars (founder decisions 2026-07-18).

Deterministic, self-referential, NO LLM: emphasis / pace_fast / pace_slow /
pause vs the speaker's OWN reference. Pinned here:

  * the detector's z-threshold matrix + strongest-|z| one-per-piece rule;
  * baseline resolution per decision BE-1a(b): cross-take history first,
    within-take means at >= 6 pieces, else SILENT;
  * feature-name normalization (raw metrics vs readout `features` names);
  * structural-intensity ordering (flattest first — founder #5);
  * the take-1/2 nudge on the ready bubble (soft nudge, never a counter);
  * priority: acoustic > delivery > structural, one star per snippet.

Run: python3 -m unittest test_delivery_stars
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.delivery_stars import (
    DELIVERY_DEVICES,
    detect_delivery_issue,
    emphasis_z,
    feature_stats,
    normalize_features,
    resolve_delivery_baseline,
)

# A flat baseline: every feature mean 10, sd 2 → z = (v - 10) / 2.
BASE = {"f0_sd": (10.0, 2.0), "dynamic_db": (10.0, 2.0),
        "wpm": (10.0, 2.0), "pause_ratio": (10.0, 2.0)}


def _m(**over):
    m = {"f0_sd": 10.0, "dynamic_db": 10.0, "wpm": 10.0, "pause_ratio": 10.0}
    m.update(over)
    return m


class DetectorTests(unittest.TestCase):
    def test_neutral_piece_no_star(self):
        self.assertIsNone(detect_delivery_issue(_m(), BASE))

    def test_flat_f0_fires_emphasis(self):
        self.assertEqual(
            detect_delivery_issue(_m(f0_sd=7.0), BASE), "emphasis")  # z=-1.5

    def test_flat_loudness_fires_emphasis(self):
        self.assertEqual(
            detect_delivery_issue(_m(dynamic_db=7.0), BASE), "emphasis")

    def test_fast_and_slow_pace(self):
        self.assertEqual(
            detect_delivery_issue(_m(wpm=13.0), BASE), "pace_fast")
        self.assertEqual(
            detect_delivery_issue(_m(wpm=7.0), BASE), "pace_slow")

    def test_low_pause_ratio_fires_pause(self):
        self.assertEqual(
            detect_delivery_issue(_m(pause_ratio=7.0), BASE), "pause")

    def test_one_sided_directions(self):
        # louder / more pauses than usual are NOT coached
        self.assertIsNone(detect_delivery_issue(_m(dynamic_db=15.0), BASE))
        self.assertIsNone(detect_delivery_issue(_m(pause_ratio=15.0), BASE))

    def test_strongest_z_wins_one_per_piece(self):
        # pace z=+2.5 beats emphasis z=-1.5
        self.assertEqual(
            detect_delivery_issue(_m(f0_sd=7.0, wpm=15.0), BASE),
            "pace_fast")

    def test_threshold_respected(self):
        self.assertIsNone(
            detect_delivery_issue(_m(f0_sd=8.0), BASE))          # z=-1.0
        self.assertEqual(
            detect_delivery_issue(_m(f0_sd=8.0), BASE,
                                  z_threshold=0.9), "emphasis")

    def test_no_baseline_or_features_silent(self):
        self.assertIsNone(detect_delivery_issue(_m(), None))
        self.assertIsNone(detect_delivery_issue({}, BASE))
        self.assertIsNone(detect_delivery_issue(None, BASE))

    def test_devices_are_the_closed_set(self):
        self.assertEqual(DELIVERY_DEVICES,
                         ("emphasis", "pace_fast", "pace_slow", "pause"))


class NormalizationTests(unittest.TestCase):
    def test_readout_feature_names_fold_to_canonical(self):
        out = normalize_features({"speech_rate": 12.0,
                                  "loudness_range": 9.0,
                                  "f0_sd": 11.0, "pause_ratio": 8.0,
                                  "mean_pause": 250, "bool_trap": True})
        self.assertEqual(out, {"wpm": 12.0, "dynamic_db": 9.0,
                               "f0_sd": 11.0, "pause_ratio": 8.0})

    def test_detector_accepts_readout_names(self):
        self.assertEqual(
            detect_delivery_issue({"speech_rate": 15.0}, BASE), "pace_fast")


class BaselineResolutionTests(unittest.TestCase):
    class _Db:
        def __init__(self, hist_pieces):
            self._hist = hist_pieces

        def v2_list_user_lab_sessions(self, uid, limit=5):
            return [{"id": "h1"}] if self._hist else []

        def get_snippets_by_session(self, sid):
            return [{"metrics": m} for m in self._hist]

    def test_history_wins(self):
        hist = [_m(f0_sd=10 + i * 0.1) for i in range(10)]
        base = resolve_delivery_baseline("u1", [], database=self._Db(hist))
        self.assertIsNotNone(base)
        self.assertIn("f0_sd", base)

    def test_within_take_fallback_at_six_pieces(self):
        cur = [_m(wpm=10 + i) for i in range(6)]
        base = resolve_delivery_baseline("u1", cur, database=self._Db([]))
        self.assertIsNotNone(base)
        self.assertIn("wpm", base)

    def test_short_take_one_is_silent(self):
        cur = [_m() for _ in range(4)]
        self.assertIsNone(
            resolve_delivery_baseline("u1", cur, database=self._Db([])))

    def test_guest_uses_within_take(self):
        cur = [_m(wpm=10 + i) for i in range(7)]
        base = resolve_delivery_baseline(None, cur, database=None)
        self.assertIsNotNone(base)

    def test_zero_spread_feature_dropped(self):
        stats = feature_stats([_m() for _ in range(8)], min_samples=6)
        self.assertIsNone(stats)   # identical values → sd 0 everywhere


class EmphasisZOrderingTests(unittest.TestCase):
    def test_flatter_sorts_first(self):
        flat = emphasis_z(_m(f0_sd=6.0), BASE)      # z=-2.0
        lively = emphasis_z(_m(f0_sd=12.0), BASE)   # z=+1.0
        self.assertLess(flat, lively)

    def test_unmeasurable_is_none(self):
        self.assertIsNone(emphasis_z({}, BASE))
        self.assertIsNone(emphasis_z(_m(), None))


class GenerateDeliveryTests(unittest.TestCase):
    class _Db:
        def __init__(self):
            self.rows = []

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.rows.append((snip, kind, trig, repl, why))
            return True

    def _run(self, candidates, *, flag="1"):
        from services.moment_suggestions import _generate_delivery
        db = self._Db()
        with patch.dict("os.environ", {"DELIVERY_STARS_ENABLED": flag}):
            starred = _generate_delivery(db, "a1", candidates, BASE)
        return starred, db.rows

    def test_persists_device_no_prose(self):
        starred, rows = self._run([("s1", _m(f0_sd=7.0))])
        self.assertEqual(starred, ["s1"])
        snip, kind, trig, repl, why = rows[0]
        self.assertEqual((kind, trig), ("delivery", "emphasis"))
        self.assertIsNone(repl)
        self.assertIsNone(why)     # copy lives FE-side, keyed by device

    def test_cap_respected(self):
        # Config attrs freeze at import (env is read once) → patch the
        # attribute, not the environment.
        from config import Config
        cands = [(f"s{i}", _m(f0_sd=7.0)) for i in range(6)]
        with patch.dict("os.environ", {"DELIVERY_STARS_ENABLED": "1"}), \
             patch.object(Config, "DELIVERY_STARS_MAX_PER_TAKE", 2):
            from services.moment_suggestions import _generate_delivery
            db = self._Db()
            starred = _generate_delivery(db, "a1", cands, BASE)
        self.assertEqual(len(starred), 2)

    def test_flag_off_stores_nothing(self):
        starred, rows = self._run([("s1", _m(f0_sd=7.0))], flag="0")
        self.assertEqual((starred, rows), ([], []))

    def test_no_baseline_stores_nothing(self):
        from services.moment_suggestions import _generate_delivery
        with patch.dict("os.environ", {"DELIVERY_STARS_ENABLED": "1"}):
            self.assertEqual(
                _generate_delivery(self._Db(), "a1",
                                   [("s1", _m(f0_sd=7.0))], None), [])


class NudgeCopyTests(unittest.TestCase):
    def _fire(self, count):
        from services.arc_notifications import fire_ideal_version_ready
        captured = {}

        class _Db:
            def insert_lounge_messages(self, uid, msgs):
                captured["body"] = msgs[0]["body"]
                return msgs

        fire_ideal_version_ready(_Db(), "u1", "a1", 1,
                                 spoken_take_count=count)
        return captured["body"]

    def test_takes_one_and_two_carry_the_nudge(self):
        for n in (1, 2):
            body = self._fire(n)
            self.assertIn("three is where it really lands", body)
            self.assertNotIn("of 3", body)       # a nudge, never a counter

    def test_take_three_plus_and_unknown_do_not(self):
        for n in (3, 7, None):
            self.assertNotIn("three is where it really lands", self._fire(n))


if __name__ == "__main__":
    unittest.main()
