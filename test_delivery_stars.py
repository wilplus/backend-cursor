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
from types import SimpleNamespace
from unittest.mock import patch

from services.delivery_stars import (
    DELIVERY_DEVICES,
    arousal_z,
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
                         ("emphasis", "pace_fast", "pace_slow", "pause",
                          "congruence", "impeccable"))

    def test_the_PRAISE_device_is_never_detected_here(self):
        # `impeccable` is in the vocabulary so the serve can render it, but
        # this detector is one-sided by construction — it looks for flatness,
        # rushing, dragging and over-pausing, and nothing else. The praise
        # decision reads the full seven-cue set and lives in
        # services/delivery_cues.py; a detector that could return it from
        # four one-sided z-tests would be praising on the absence of a
        # complaint.
        import inspect

        from services import delivery_stars as ds
        self.assertNotIn("impeccable",
                         inspect.getsource(ds.detect_delivery_issue))


class PraiseShortCircuitsTheComplaintTests(unittest.TestCase):
    """Founder 2026-08-15: "if the delivery was impeccable, just give them
    the feedback in the praise lane."

    The load-bearing half is the SHORT-CIRCUIT. detect_delivery_issue is
    one-sided, so on a well-delivered moment it returns either nothing or
    whichever complaint sat closest to its threshold — and handing that to
    somebody who just nailed it is the note this replaces."""

    class _Db:
        def __init__(self):
            self.rows = []

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig,
                                     **kw):
            self.rows.append((snip, kind, trig, kw.get("cue_keys")))
            return True

    # Unit-sd baselines so a feature value reads as its own z.
    CUE_BASE = {k: (10.0, 1.0) for k in
                ("f0_sd", "dynamic_db", "pause_ratio", "pause_ms", "f0_mean",
                 "wpm", "f0_mid_end_delta", "intensity_envelope")}
    DELIV_BASE = {k: (10.0, 1.0) for k in
                  ("f0_sd", "dynamic_db", "wpm", "pause_ratio")}

    def _run(self, metrics, **kw):
        import os
        from unittest.mock import patch

        from services import moment_suggestions as ms
        db = self._Db()
        kw.setdefault("cue_baseline", self.CUE_BASE)
        with patch.dict(os.environ, {"DELIVERY_STARS_ENABLED": "1"}):
            ms._generate_delivery(db, "arc-1", [("s1", metrics)],
                                  self.DELIV_BASE, **kw)
        return db.rows

    def test_an_impeccable_delivery_is_PRAISED_not_complained_about(self):
        # Wide range + full volume + no hesitation, AND flat enough on the
        # delivery detector's own axes that it would have said "emphasis".
        rows = self._run({"f0_sd": 12.0, "dynamic_db": 12.0,
                          "pause_ratio": 8.0, "pause_ms": 8.0,
                          "voice_confidence": {"score": 0.85}},
                         sex="female")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "impeccable")
        self.assertIn("wide_range", rows[0][3])

    def test_a_MIDDLING_delivery_still_gets_its_note(self):
        # The praise gate must not swallow the to-work-on lane: this one is
        # genuinely flat and should still hear about it.
        rows = self._run({"f0_sd": 7.0, "dynamic_db": 7.0,
                          "voice_confidence": {"score": 0.0}},
                         sex="female")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "emphasis")
        self.assertIsNone(rows[0][3])

    def test_a_BORDERLINE_read_is_not_praised(self):
        rows = self._run({"f0_sd": 12.0, "dynamic_db": 12.0,
                          "pause_ratio": 8.0, "pause_ms": 8.0,
                          "voice_confidence": {"score": 0.3}},
                         sex="female")
        self.assertNotEqual(rows[0][2] if rows else None, "impeccable")

    def test_no_confidence_baseline_no_praise(self):
        rows = self._run({"f0_sd": 12.0, "dynamic_db": 12.0,
                          "voice_confidence": {"score": 0.9}},
                         sex="female", cue_baseline=None)
        self.assertNotEqual(rows[0][2] if rows else None, "impeccable")

    def test_the_raw_metrics_win_over_the_readout_spelling(self):
        # Cue and baseline must be measured off one source; metrics_by_id is
        # the blob the confidence baseline was built from.
        rows = self._run({"f0_sd": 7.0},   # readout copy says flat …
                         sex="female",
                         metrics_by_id={"s1": {
                             "f0_sd": 12.0, "dynamic_db": 12.0,
                             "pause_ratio": 8.0, "pause_ms": 8.0,
                             "voice_confidence": {"score": 0.9}}})
        self.assertEqual(rows[0][2], "impeccable")   # … the raw blob decides


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

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig, **_kw):
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

    def test_no_take_carries_the_nudge_any_more(self):
        # Founder 2026-08-05: "not text that it really lands on the 3rd
        # time; on the bubble never; just the title, date and the CTA."
        # The bubble is read once on arrival and a hundred times on
        # scroll-back — a nudge stamped into it is noise by the third read.
        for n in (1, 2, 3, 7, None):
            body = self._fire(n)
            self.assertNotIn("three is where it really lands", body)
            self.assertNotIn("of 3", body)       # never a counter (AC-9)

    def test_the_body_is_one_short_line_whatever_the_take(self):
        for n in (1, 2, 3, 7, None):
            self.assertEqual(self._fire(n), "Your ideal text is ready.")


class ArousalZTests(unittest.TestCase):
    """The baseline-relative ACTIVATION composite (Juslin & Laukka, 2003):
    fast + loud + pitch-mobile + un-paused → high; slow + soft + flat +
    paused → low. Graded (not a threshold); arousal axis only, never emotion."""

    def test_neutral_piece_is_zero(self):
        self.assertEqual(arousal_z(_m(), BASE), 0.0)

    def test_high_arousal_is_clearly_positive(self):
        # every cue pushed toward activation (pause_ratio DOWN)
        av = arousal_z(_m(wpm=14, dynamic_db=14, f0_sd=14, pause_ratio=6), BASE)
        self.assertEqual(av, 2.0)          # mean of +2 on all four

    def test_low_arousal_is_clearly_negative(self):
        av = arousal_z(_m(wpm=6, dynamic_db=6, f0_sd=6, pause_ratio=14), BASE)
        self.assertEqual(av, -2.0)

    def test_more_pauses_lower_arousal(self):
        # pause_ratio is the ONE inverted cue: more silence = calmer
        self.assertEqual(arousal_z({"pause_ratio": 14.0}, BASE), -2.0)
        self.assertEqual(arousal_z({"pause_ratio": 6.0}, BASE), 2.0)

    def test_partial_features_average_what_is_present(self):
        self.assertEqual(arousal_z({"wpm": 14.0}, BASE), 2.0)   # mean of one

    def test_graded_not_thresholded(self):
        strong = arousal_z(_m(wpm=14, dynamic_db=14, f0_sd=14, pause_ratio=6),
                           BASE)
        mild = arousal_z(_m(wpm=12, dynamic_db=12, f0_sd=12, pause_ratio=8),
                         BASE)
        self.assertGreater(strong, mild)   # closeness wins, not just "over"

    def test_unmeasurable_is_none(self):
        self.assertIsNone(arousal_z(_m(), None))     # no baseline
        self.assertIsNone(arousal_z({}, BASE))       # no features
        self.assertIsNone(arousal_z(None, BASE))


class SetSnippetArousalCaptureTests(unittest.TestCase):
    """db.set_snippet_arousal — best-effort capture; a pending column (or any
    error) must return False, never raise into the analysis path."""

    class _Chain:
        def __init__(self, *, raises=False, data=None):
            self._raises = raises
            self._data = data
            self.payload = None

        def table(self, name):
            return self

        def update(self, payload):
            self.payload = payload
            return self

        def eq(self, col, val):
            return self

        def execute(self):
            if self._raises:
                raise RuntimeError('column "arousal_z" does not exist')
            return SimpleNamespace(data=self._data)

    def _set(self, chain):
        from services.db import DatabaseService
        fake = SimpleNamespace(client=chain)
        return DatabaseService.set_snippet_arousal(fake, "snip-1", 1.5)

    def test_success_writes_the_column_and_reports_true(self):
        chain = self._Chain(data=[{"id": "snip-1"}])
        self.assertTrue(self._set(chain))
        self.assertEqual(chain.payload, {"arousal_z": 1.5})

    def test_missing_column_is_swallowed(self):
        self.assertFalse(self._set(self._Chain(raises=True)))

    def test_no_rows_reports_false(self):
        self.assertFalse(self._set(self._Chain(data=[])))


if __name__ == "__main__":
    unittest.main()
