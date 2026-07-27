"""willab — the voice-confidence composite (founder spec 2026-07-27, Jiang &
Pell 2017) and its entry into the L2 ranking blend.

services/voice_confidence.py: the 7-cue speaker-relative confident↔doubtful
read; services/power_phrase_ranking.py: the new w_v term.

WHAT THIS PINS DOWN:
  * every cue's DIRECTION, one at a time — the whole spec is directions, so a
    silently inverted sign is the failure mode that matters. Cue 6
    (f0_mid_end_delta) is tested explicitly because our field is
    ``mid - end``, which inverts the spec sheet's wording;
  * the NEUTRAL DEAD ZONE — a middling clip must read 0.0, not be forced to a
    pole;
  * partial-blob RENORMALIZATION — a piece missing cues must not drift toward
    neutral just because features were absent;
  * SILENCE over invention — no baseline / too few cues → None, never 0.0;
  * the ranking is a strict NO-OP until the flag is on (byte-for-byte), and
    the authority ordering (coach > breakthrough > delivery) survives the new
    term;
  * AC-9 — the score/band never reach a user OR coach payload.

Run: python3 -m unittest test_voice_confidence
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


# A baseline where every feature has mean 0.0 and sd 1.0, so a raw metric value
# IS its z-score — the cue directions become readable by eye.
_UNIT_BASELINE = {
    "f0_sd": (0.0, 1.0),
    "dynamic_db": (0.0, 1.0),
    "f0_mean": (0.0, 1.0),
    "wpm": (0.0, 1.0),
    "pause_ratio": (0.0, 1.0),
    "pause_ms": (0.0, 1.0),
    "f0_mid_end_delta": (0.0, 1.0),
    "intensity_envelope": (0.0, 1.0),
}

# Neutral on every cue — the base each single-cue test perturbs.
_FLAT = {k: 0.0 for k in _UNIT_BASELINE}


def _with(**over) -> dict:
    m = dict(_FLAT)
    m.update(over)
    return m


class TestCueDirections(unittest.TestCase):
    """Each cue, moved alone, must push the composite the way the paper says."""

    def _score(self, metrics) -> float:
        from services.voice_confidence import confidence_z
        result = confidence_z(metrics, _UNIT_BASELINE)
        self.assertIsNotNone(result, "expected a measurable read")
        return result[0]

    def test_flat_baseline_reads_zero(self):
        self.assertAlmostEqual(self._score(_FLAT), 0.0, places=6)

    def test_wider_pitch_range_is_more_confident(self):
        # Cue 1 — f0_sd, wider → confident (Table 3: 1.32 vs 1.09).
        self.assertGreater(self._score(_with(f0_sd=2.0)), 0.0)
        self.assertLess(self._score(_with(f0_sd=-2.0)), 0.0)

    def test_wider_loudness_range_is_more_confident(self):
        # Cue 2 — dynamic_db, Tier-A (Table 3: 1.47 vs 1.17).
        self.assertGreater(self._score(_with(dynamic_db=2.0)), 0.0)
        self.assertLess(self._score(_with(dynamic_db=-2.0)), 0.0)

    def test_higher_mean_pitch_is_less_confident(self):
        # Cue 3 — f0_mean INVERTED (Table 3: 0.51 vs 0.70, beta=+.74 to doubt).
        self.assertLess(self._score(_with(f0_mean=2.0)), 0.0)
        self.assertGreater(self._score(_with(f0_mean=-2.0)), 0.0)

    def test_faster_speech_is_more_confident(self):
        # Cue 4 — wpm (Table 3 duration: 1.11 confident vs 1.38 unconfident).
        self.assertGreater(self._score(_with(wpm=2.0)), 0.0)
        self.assertLess(self._score(_with(wpm=-2.0)), 0.0)

    def test_more_pausing_is_less_confident(self):
        # Cue 5 — pausing INVERTED, Tier-A.
        self.assertLess(self._score(_with(pause_ratio=2.0, pause_ms=2.0)), 0.0)
        self.assertGreater(
            self._score(_with(pause_ratio=-2.0, pause_ms=-2.0)), 0.0)

    def test_pausing_counts_once_across_its_two_features(self):
        """pause_ms and pause_ratio are ONE cue (the spec's 'pause_ms OR
        pause_ratio'), so carrying both must not double its weight. Built from
        bare dicts, not _with(), so the absent feature is genuinely ABSENT —
        a present-but-zero pause_ms would average the cue down and mask this."""
        both = abs(self._score(
            {"pause_ratio": 2.0, "pause_ms": 2.0, "f0_sd": 0.0,
             "dynamic_db": 0.0}))
        one = abs(self._score(
            {"pause_ratio": 2.0, "f0_sd": 0.0, "dynamic_db": 0.0}))
        self.assertAlmostEqual(both, one, places=6)
        self.assertGreater(both, 0.0)

    def test_falling_terminal_contour_is_more_confident(self):
        """Cue 6 — THE sign trap. f0_mid_end_delta is mean(middle third) -
        mean(last third), so a voice that FALLS at the end yields a POSITIVE
        delta. Falling terminal = confident, therefore positive = confident —
        the opposite of the spec sheet's literal wording, which assumed the
        other convention."""
        falls_at_end = _with(f0_mid_end_delta=2.0)     # middle > end
        rises_at_end = _with(f0_mid_end_delta=-2.0)    # end > middle
        self.assertGreater(self._score(falls_at_end), 0.0)
        self.assertLess(self._score(rises_at_end), 0.0)

    def test_front_loaded_energy_is_more_confident(self):
        """Cue 7 — intensity_envelope is a dB/sec slope where POSITIVE means
        loudness builds toward the end. Front-loaded/decaying = negative slope
        = confident, so the cue is inverted."""
        decaying = _with(intensity_envelope=-2.0)
        building = _with(intensity_envelope=2.0)
        self.assertGreater(self._score(decaying), 0.0)
        self.assertLess(self._score(building), 0.0)

    def test_tier_a_cues_outweigh_the_contour_cues(self):
        """The weights tilt toward what our extraction measures most reliably."""
        tier_a = abs(self._score(_with(dynamic_db=2.0)))
        contour = abs(self._score(_with(f0_mid_end_delta=2.0)))
        self.assertGreater(tier_a, contour)


class TestSpectrumAndDeadZone(unittest.TestCase):

    def test_dead_zone_keeps_middling_clips_neutral(self):
        from services.voice_confidence import to_spectrum
        self.assertEqual(to_spectrum(0.0), 0.0)
        self.assertEqual(to_spectrum(0.2), 0.0)
        self.assertEqual(to_spectrum(-0.2), 0.0)

    def test_outside_the_dead_zone_leans_continuously(self):
        from services.voice_confidence import to_spectrum
        # Just outside → barely leaning, not pegged (the "close-to-confident"
        # band the paper shows).
        self.assertGreater(to_spectrum(0.3), 0.0)
        self.assertLess(to_spectrum(0.3), 0.15)
        # Strongly atypical → a real lean, still bounded.
        self.assertGreater(to_spectrum(2.0), 0.8)
        self.assertLess(to_spectrum(2.0), 1.0)

    def test_spectrum_is_bounded_and_symmetric(self):
        from services.voice_confidence import to_spectrum
        for z in (-9.0, -3.0, -1.0, 1.0, 3.0, 9.0):
            self.assertGreaterEqual(to_spectrum(z), -1.0)
            self.assertLessEqual(to_spectrum(z), 1.0)
            self.assertAlmostEqual(to_spectrum(z), -to_spectrum(-z), places=6)

    def test_band_is_the_five_point_spectrum(self):
        from services.voice_confidence import band
        self.assertEqual(band(0.0), "neutral")
        self.assertEqual(band(0.2), "close_to_confident")
        self.assertEqual(band(0.8), "confident")
        self.assertEqual(band(-0.2), "unconfident")
        self.assertEqual(band(-0.8), "doubtful")
        self.assertIsNone(band(None))
        self.assertIsNone(band(True))   # bool is not a score


class TestPartialAndMissingData(unittest.TestCase):

    def test_partial_blob_is_renormalized_not_shrunk(self):
        """A piece carrying only 3 cues must sit on the SAME scale as one
        carrying all 7 — otherwise missing features masquerade as neutrality
        and a sparse blob would always look 'close to confident'."""
        from services.voice_confidence import confidence_z
        full = confidence_z(
            {k: 2.0 if k not in ("f0_mean", "pause_ratio", "pause_ms",
                                 "intensity_envelope") else -2.0
             for k in _UNIT_BASELINE},
            _UNIT_BASELINE)
        partial = confidence_z(
            {"f0_sd": 2.0, "dynamic_db": 2.0, "wpm": 2.0}, _UNIT_BASELINE)
        self.assertIsNotNone(full)
        self.assertIsNotNone(partial)
        # Both are "2 sd toward confident on every cue they can measure".
        self.assertAlmostEqual(full[0], 2.0, places=6)
        self.assertAlmostEqual(partial[0], 2.0, places=6)

    def test_too_few_cues_reads_none_not_zero(self):
        from services.voice_confidence import confidence_z, read_for_piece
        self.assertIsNone(confidence_z({"f0_sd": 1.0}, _UNIT_BASELINE))
        self.assertIsNone(read_for_piece({"f0_sd": 1.0}, _UNIT_BASELINE))

    def test_no_baseline_reads_none(self):
        from services.voice_confidence import confidence_z, read_for_piece
        self.assertIsNone(confidence_z(_with(f0_sd=2.0), None))
        self.assertIsNone(read_for_piece(_with(f0_sd=2.0), {}))

    def test_zero_sd_feature_is_skipped_not_divided_by(self):
        """A baseline feature with no spread carries no signal — it must be
        dropped (not divided by, and not silently read as an enormous z)."""
        from services.voice_confidence import confidence_z
        base = dict(_UNIT_BASELINE)
        base["f0_sd"] = (0.0, 0.0)
        wild = confidence_z(_with(f0_sd=500.0, dynamic_db=1.0), base)
        tame = confidence_z(_with(f0_sd=0.0, dynamic_db=1.0), base)
        self.assertIsNotNone(wild)
        self.assertEqual(wild, tame)     # f0_sd contributed nothing either way
        self.assertEqual(wild[1], 6)     # 7 cues minus the dead one

    def test_readout_feature_spelling_is_accepted(self):
        """best_presentation reads `metrics`; the readout hands over `features`
        with three keys renamed. Both must land on the same read."""
        from services.voice_confidence import confidence_z
        raw = confidence_z(
            {"f0_sd": 2.0, "dynamic_db": 2.0, "wpm": 2.0}, _UNIT_BASELINE)
        renamed = confidence_z(
            {"f0_sd": 2.0, "loudness_range": 2.0, "speech_rate": 2.0},
            _UNIT_BASELINE)
        self.assertEqual(raw, renamed)


class TestAttach(unittest.TestCase):

    def _pieces(self, n=6):
        return [{"metrics": _with(f0_sd=float(i))} for i in range(n)]

    def test_attach_stamps_every_measurable_piece(self):
        from services.voice_confidence import attach_voice_confidence
        pieces = self._pieces()
        attach_voice_confidence(pieces, baseline=_UNIT_BASELINE,
                                baseline_kind="user")
        for p in pieces:
            read = p["metrics"]["voice_confidence"]
            self.assertEqual(read["version"], "voice-confidence-v1")
            self.assertEqual(read["baseline"], "user")
            self.assertIn(read["band"], (
                "confident", "close_to_confident", "neutral",
                "unconfident", "doubtful"))
            self.assertGreaterEqual(read["score"], -1.0)
            self.assertLessEqual(read["score"], 1.0)

    def test_attach_without_baseline_stamps_nothing(self):
        from services.voice_confidence import attach_voice_confidence
        pieces = self._pieces()
        attach_voice_confidence(pieces, baseline=None)
        for p in pieces:
            self.assertNotIn("voice_confidence", p["metrics"])

    def test_attach_never_raises_on_junk(self):
        from services.voice_confidence import attach_voice_confidence
        attach_voice_confidence(None, baseline=_UNIT_BASELINE)
        attach_voice_confidence([None, 7, {}, {"metrics": None}],
                                baseline=_UNIT_BASELINE)

    def test_deterministic(self):
        from services.voice_confidence import read_for_piece
        m = _with(f0_sd=1.5, dynamic_db=-0.5, wpm=2.0)
        self.assertEqual(read_for_piece(m, _UNIT_BASELINE),
                         read_for_piece(m, _UNIT_BASELINE))


class TestBaselineResolution(unittest.TestCase):

    def test_within_take_needs_six_pieces(self):
        from services.voice_confidence import resolve_confidence_baseline
        five = [_with(f0_sd=float(i)) for i in range(5)]
        base, kind = resolve_confidence_baseline(None, five)
        self.assertIsNone(base)
        self.assertEqual(kind, "none")

        six = [_with(f0_sd=float(i), dynamic_db=float(i)) for i in range(6)]
        base, kind = resolve_confidence_baseline(None, six)
        self.assertIsNotNone(base)
        self.assertEqual(kind, "take")

    def test_cross_take_history_wins_over_within_take(self):
        from services.voice_confidence import resolve_confidence_baseline
        db = MagicMock()
        db.v2_list_user_lab_sessions.return_value = [{"id": "s1"}]
        db.get_snippets_by_session.return_value = [
            {"metrics": _with(f0_sd=float(i), dynamic_db=float(i))}
            for i in range(10)
        ]
        base, kind = resolve_confidence_baseline(
            "u1", [_with(f0_sd=float(i)) for i in range(6)], database=db)
        self.assertIsNotNone(base)
        self.assertEqual(kind, "user")

    def test_db_failure_falls_back_never_raises(self):
        from services.voice_confidence import resolve_confidence_baseline
        db = MagicMock()
        db.v2_list_user_lab_sessions.side_effect = RuntimeError("boom")
        six = [_with(f0_sd=float(i), dynamic_db=float(i)) for i in range(6)]
        base, kind = resolve_confidence_baseline("u1", six, database=db)
        self.assertEqual(kind, "take")
        self.assertIsNotNone(base)


class TestRankTermFlag(unittest.TestCase):

    _STAMPED = {"voice_confidence": {"score": 0.7, "band": "confident",
                                     "baseline": "user", "cues": 7,
                                     "version": "voice-confidence-v1"}}

    def test_flag_off_is_none(self):
        from services.voice_confidence import rank_term
        with patch.dict("os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "0"}):
            self.assertIsNone(rank_term(self._STAMPED))

    def test_flag_default_is_off(self):
        from services.voice_confidence import rank_term
        import os
        env = {k: v for k, v in os.environ.items()
               if k != "VOICE_CONFIDENCE_RANKING_ENABLED"}
        with patch.dict("os.environ", env, clear=True):
            self.assertIsNone(rank_term(self._STAMPED))

    def test_flag_on_returns_the_score(self):
        from services.voice_confidence import rank_term
        with patch.dict("os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            self.assertEqual(rank_term(self._STAMPED), 0.7)

    def test_unstamped_piece_is_none_even_with_the_flag_on(self):
        from services.voice_confidence import rank_term
        with patch.dict("os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            self.assertIsNone(rank_term({}))
            self.assertIsNone(rank_term(None))
            self.assertIsNone(rank_term({"voice_confidence": "junk"}))
            self.assertIsNone(rank_term({"voice_confidence": {"score": None}}))


class TestPowerScoreBlend(unittest.TestCase):

    def test_absent_term_is_byte_for_byte_no_op(self):
        """Every pre-existing caller passes no voice_confidence; their score
        must be identical to before the term existed."""
        from services.power_phrase_ranking import power_score
        for kwargs in (
            {"activation": 0.8, "slide_stickiness": 0.5},
            {"tag": "strong", "activation": 0.2},
            {"direction": "challenge", "breakthrough": True},
            {"rank": 2},
        ):
            self.assertEqual(power_score(**kwargs),
                             power_score(voice_confidence=None, **kwargs))

    def test_confidence_lifts_and_doubt_drops(self):
        from services.power_phrase_ranking import power_score
        base = power_score(activation=0.5, slide_stickiness=0.5)
        up = power_score(activation=0.5, slide_stickiness=0.5,
                         voice_confidence=0.9)
        down = power_score(activation=0.5, slide_stickiness=0.5,
                           voice_confidence=-0.9)
        self.assertGreater(up, base)
        self.assertLess(down, base)

    def test_stickiness_still_counts(self):
        """The founder ask: confidence is ONE thing, topic stickiness ANOTHER,
        combined. A confident-but-off-topic moment must not automatically beat
        a less confident one that covered the slide."""
        from services.power_phrase_ranking import power_score
        confident_offtopic = power_score(
            activation=0.0, slide_stickiness=0.0, voice_confidence=1.0)
        flat_ontopic = power_score(
            activation=1.0, slide_stickiness=1.0, voice_confidence=0.0)
        self.assertGreater(flat_ontopic, confident_offtopic)

    def test_coach_verdict_still_dominates_delivery(self):
        from services.power_phrase_ranking import power_score
        coach_strong_but_doubtful = power_score(tag="strong",
                                                voice_confidence=-1.0)
        coach_towork_but_confident = power_score(tag="to_work_on",
                                                 voice_confidence=1.0)
        self.assertGreater(coach_strong_but_doubtful,
                           coach_towork_but_confident)

    def test_breakthrough_still_outranks_delivery(self):
        from services.power_phrase_ranking import power_score
        self.assertGreater(power_score(breakthrough=True, voice_confidence=0.0),
                           power_score(breakthrough=False, voice_confidence=1.0))

    def test_junk_value_is_neutral(self):
        from services.power_phrase_ranking import power_score
        base = power_score(activation=0.5)
        for junk in ("0.9", True, None, [], {}):
            self.assertEqual(power_score(activation=0.5,
                                         voice_confidence=junk), base)


class TestSelectionUsesTheTerm(unittest.TestCase):

    def _cand(self, si, sid, text, confidence):
        return {"slide_index": si, "snippet_id": sid, "transcript": text,
                "activation": 0.5, "slide_stickiness": 0.5,
                "voice_confidence": confidence}

    def test_more_confident_delivery_wins_a_tied_slide(self):
        from services.best_presentation import select_best_per_slide
        picks = select_best_per_slide([
            self._cand(0, "flat", "We tripled revenue this year.", -0.8),
            self._cand(0, "sure", "We tripled revenue this year again.", 0.8),
        ])
        self.assertEqual(picks[0]["snippet_id"], "sure")

    def test_none_confidence_does_not_penalise_a_piece(self):
        """Unstamped (older) pieces must compete on the other terms, not be
        treated as maximally doubtful."""
        from services.best_presentation import select_best_per_slide
        picks = select_best_per_slide([
            {"slide_index": 0, "snippet_id": "old", "transcript": "Strong line.",
             "activation": 0.9, "slide_stickiness": 0.9,
             "voice_confidence": None},
            {"slide_index": 0, "snippet_id": "new", "transcript": "Weak line.",
             "activation": 0.1, "slide_stickiness": 0.1,
             "voice_confidence": 0.3},
        ])
        self.assertEqual(picks[0]["snippet_id"], "old")


class TestFences(unittest.TestCase):

    def test_score_never_reaches_a_user_or_coach_payload(self):
        """AC-9 + BLIND COACH. The readout serializer is an allowlist, so the
        stamped blob must not appear on either branch — the user readout OR the
        coach packet (include_slide_scores). This one is a source-level fence
        because a future 'just pass metrics through' would silently breach it."""
        with open("services/lab_recording.py", encoding="utf-8") as fh:
            source = fh.read()
        serializer = source.split("def build_readout_from_session")[1]
        self.assertNotIn('snip_out["voice_confidence"]', serializer)
        self.assertNotIn('"voice_confidence"', serializer.split(
            "out_snips.append")[0])

    def test_composite_is_not_learned(self):
        """The weights are constants — no model, no fitting, nothing that could
        anchor a labeling coach to a machine opinion."""
        with open("services/voice_confidence.py", encoding="utf-8") as fh:
            source = fh.read()
        for banned in ("learning_serve", "predict_direction", "joblib",
                       "sklearn", "fit("):
            self.assertNotIn(banned, source)

    def test_acoustic_read_is_untouched_by_this_lane(self):
        """Founder decision: the coach's stress↔charisma needle stays as-is;
        this composite is ranking-internal and must not import or mutate it."""
        with open("services/voice_confidence.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("acoustic_read", source.replace(
            "services/acoustic_read.py", ""))


if __name__ == "__main__":
    unittest.main()
