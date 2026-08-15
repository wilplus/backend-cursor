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
            self.assertEqual(read["version"], "voice-confidence-v2")
            self.assertEqual(read["baseline"], "user")
            # Un-resolved sex is stamped honestly, not left absent.
            self.assertEqual(read["sex"], "unknown")
            self.assertEqual(read["sex_source"], "unknown")
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
                                     "sex": "male", "sex_source": "declared",
                                     "version": "voice-confidence-v2"}}

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

    def test_a_superseded_weighting_does_not_rank(self):
        """THE mixed-basis guard. A v1 stamp scored a wide pitch range as
        +0.18*z for everyone; v2 SUBTRACTS 0.08*z for a man. Ranking the two
        against each other is comparing different scales that both look
        plausible — so the older weighting sits out until it is backfilled."""
        from services.voice_confidence import rank_term
        stale = {"voice_confidence": {"score": 0.7, "band": "confident",
                                      "baseline": "user", "cues": 7,
                                      "version": "voice-confidence-v1"}}
        with patch.dict("os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            self.assertIsNone(rank_term(stale))
            self.assertEqual(rank_term(self._STAMPED), 0.7)   # current: ranks

    def test_a_missing_version_does_not_rank(self):
        """Pre-versioning blobs are pre-v2 by definition."""
        from services.voice_confidence import rank_term
        with patch.dict("os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            self.assertIsNone(rank_term({"voice_confidence": {"score": 0.7}}))

    def test_the_rankable_set_tracks_the_current_version(self):
        """A _VERSION bump must not silently leave the old one rankable — the
        whole point is that a weighting change takes its stamps out of the
        ranking until they are backfilled."""
        from services.voice_confidence import _RANKABLE_VERSIONS, _VERSION
        self.assertIn(_VERSION, _RANKABLE_VERSIONS)
        self.assertEqual(len(_RANKABLE_VERSIONS), 1)

    def test_unstamped_piece_is_none_even_with_the_flag_on(self):
        from services.voice_confidence import rank_term
        with patch.dict("os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            self.assertIsNone(rank_term({}))
            self.assertIsNone(rank_term(None))
            self.assertIsNone(rank_term({"voice_confidence": "junk"}))
            self.assertIsNone(rank_term({"voice_confidence": {"score": None}}))


class TestPowerScoreBlend(unittest.TestCase):

    def test_absent_term_is_byte_for_byte_no_op(self):
        """Every pre-existing caller passes no confidence; their score must be
        identical to before the term existed."""
        from services.power_phrase_ranking import power_score
        for kwargs in (
            {"activation": 0.8, "slide_stickiness": 0.5},
            {"tag": "strong", "activation": 0.2},
            {"rank": 2},
        ):
            self.assertEqual(power_score(**kwargs),
                             power_score(machine_confidence=None, **kwargs))

    def test_confidence_lifts_and_doubt_drops(self):
        from services.power_phrase_ranking import power_score
        base = power_score(activation=0.5, slide_stickiness=0.5)
        up = power_score(activation=0.5, slide_stickiness=0.5,
                         machine_confidence=0.9)
        down = power_score(activation=0.5, slide_stickiness=0.5,
                           machine_confidence=-0.9)
        self.assertGreater(up, base)
        self.assertLess(down, base)

    def test_stickiness_still_counts(self):
        """The founder ask: confidence is ONE thing, topic stickiness ANOTHER,
        combined. A confident-but-off-topic moment must not automatically beat
        a less confident one that covered the slide."""
        from services.power_phrase_ranking import power_score
        confident_offtopic = power_score(
            activation=0.0, slide_stickiness=0.0, machine_confidence=1.0)
        flat_ontopic = power_score(
            activation=1.0, slide_stickiness=1.0, machine_confidence=0.0)
        self.assertGreater(flat_ontopic, confident_offtopic)

    def test_coach_veto_still_dominates_delivery(self):
        """RE-PINNED 2026-08-14. This used to read `strong` vs `to_work_on`,
        which stopped meaning anything when the fake `strong` half of the coach
        term was deleted — no picker for it exists, so it fired on "the coach
        typed a note". The surviving claim is the one that matters and is
        stronger: on THE SAME phrase, the coach's explicit to_work_on is never
        undone by how well it was delivered. Delivery is identical on both
        sides here, so only the human verdict separates them."""
        from services.power_phrase_ranking import power_score
        for delivery in (-1.0, 0.0, 1.0):
            vetoed = power_score(tag="to_work_on", machine_confidence=delivery)
            untouched = power_score(machine_confidence=delivery)
            self.assertLess(vetoed, untouched)

    def test_the_album_quorum_bonus_is_deleted(self):
        """Founder verdict 2026-08-13 evening: `_W_B` is gone entirely. The
        retired kwarg raises like the other retired kwargs do."""
        from services.power_phrase_ranking import power_score
        with self.assertRaises(TypeError):
            power_score(album_quorum=True)

    def test_junk_value_is_neutral(self):
        from services.power_phrase_ranking import power_score
        base = power_score(activation=0.5)
        for junk in ("0.9", True, None, [], {}):
            self.assertEqual(power_score(activation=0.5,
                                         machine_confidence=junk), base)


class TestSelectionUsesTheTerm(unittest.TestCase):

    def _cand(self, si, sid, text, confidence):
        return {"slide_index": si, "snippet_id": sid, "transcript": text,
                "activation": 0.5, "slide_stickiness": 0.5,
                "machine_confidence": confidence}

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


class TestSexConditionedWeights(unittest.TestCase):
    """v2 — the cue weights route on speaker sex, and cue 1 REVERSES.

    This is the failure mode the whole feature exists for: within-speaker
    z-scoring cannot absorb a direction flip, so a sex-blind weight on f0_sd
    mis-scores one sex however well it is calibrated."""

    def _z(self, metrics, sex=None):
        from services.voice_confidence import confidence_z
        result = confidence_z(metrics, _UNIT_BASELINE, sex)
        self.assertIsNotNone(result, "expected a measurable read")
        return result[0]

    def test_wide_pitch_range_flips_sign_between_the_sexes(self):
        """THE reversal. Same clip, same baseline — opposite verdicts.
        Female: wide f0 range is the top confidence cue. Male: it trends
        UNCONFIDENT (paper: f0 variance highest in the unconfident level for
        male talkers)."""
        wide = _with(f0_sd=2.0)
        self.assertGreater(self._z(wide, "female"), 0.0)
        self.assertLess(self._z(wide, "male"), 0.0)

        narrow = _with(f0_sd=-2.0)
        self.assertLess(self._z(narrow, "female"), 0.0)
        self.assertGreater(self._z(narrow, "male"), 0.0)

    def test_every_other_cue_keeps_its_direction_in_both_tables(self):
        """Only cue 1 flips. If a re-weighting ever inverts another cue, that
        is a bug, not a tuning choice."""
        same_direction = [
            (_with(dynamic_db=2.0), +1),
            (_with(f0_mean=2.0), -1),
            (_with(wpm=2.0), +1),
            (_with(pause_ratio=2.0, pause_ms=2.0), -1),
            (_with(f0_mid_end_delta=2.0), +1),
            (_with(intensity_envelope=-2.0), +1),
        ]
        for metrics, expected in same_direction:
            for sex in (None, "female", "male"):
                z = self._z(metrics, sex)
                self.assertEqual(
                    1 if z > 0 else -1, expected,
                    f"direction changed for sex={sex} on {metrics}")

    def test_unknown_sex_reproduces_v1_scores_exactly(self):
        """The regression that protects every existing speaker. Nobody has a
        declared sex on the day this ships; their composite must not move."""
        from services.voice_confidence import _CUES, cues_for
        self.assertIs(cues_for(None), _CUES)
        self.assertIs(cues_for("prefer_not_to_say"), _CUES)
        self.assertIs(cues_for("nonsense"), _CUES)
        self.assertIs(cues_for(""), _CUES)
        # And the arithmetic agrees: the sex-blind read is the no-arg read.
        from services.voice_confidence import confidence_z
        m = _with(f0_sd=1.5, dynamic_db=-0.5, wpm=2.0, pause_ratio=0.7)
        self.assertEqual(confidence_z(m, _UNIT_BASELINE),
                         confidence_z(m, _UNIT_BASELINE, None))

    def test_both_tables_are_normalized_and_complete(self):
        """Weights must sum to 1.0 and cover the same seven cues, or the
        renormalization in confidence_z silently changes scale between sexes
        and male/female scores stop being comparable to each other."""
        from services.voice_confidence import _CUES, _CUES_FEMALE, _CUES_MALE
        blind_names = [c[0] for c in _CUES]
        for table, label in ((_CUES_FEMALE, "female"), (_CUES_MALE, "male")):
            self.assertAlmostEqual(sum(c[2] for c in table), 1.0, places=9,
                                   msg=f"{label} weights must sum to 1.0")
            self.assertEqual([c[0] for c in table], blind_names,
                             f"{label} table must cover the same cues")
            for _name, members, _w in table:
                for _feature, sign in members:
                    self.assertIn(sign, (+1.0, -1.0))

    def test_the_flipped_cue_carries_a_small_weight_for_men(self):
        """Blast-radius guard. Sex can be resolved wrongly (an inferred route,
        a mistaken answer); the one cue whose SIGN depends on that resolution
        must not be able to swing the composite on its own."""
        from services.voice_confidence import _CUES_MALE
        flipped = next(w for name, _m, w in _CUES_MALE if name == "pitch_range")
        others = [w for name, _m, w in _CUES_MALE if name != "pitch_range"]
        self.assertLessEqual(flipped, 0.10)
        self.assertLess(flipped, max(others))

    def test_male_weights_favour_loudness_and_pausing(self):
        """The paper's male pattern: confidence signalled chiefly by loudness,
        with pausing the most differentiated cue. We have no absolute mean
        loudness, so dynamic_db + front-loaded energy stand in for it."""
        from services.voice_confidence import _CUES_MALE, _CUES_FEMALE
        w_male = {n: w for n, _m, w in _CUES_MALE}
        w_female = {n: w for n, _m, w in _CUES_FEMALE}
        self.assertGreater(w_male["pausing"], w_female["pausing"])
        self.assertGreater(w_male["energy_frontload"],
                           w_female["energy_frontload"])
        # ...and the female pattern: pitch range + loudness range lead.
        self.assertGreater(w_female["pitch_range"], w_male["pitch_range"])
        self.assertGreater(w_female["loudness_range"],
                           w_female["speech_rate"])


class TestSexNormalizationAndInference(unittest.TestCase):

    def test_normalize_sex_accepts_only_the_three_values(self):
        from services.voice_confidence import normalize_sex
        self.assertEqual(normalize_sex("female"), "female")
        self.assertEqual(normalize_sex("  MALE "), "male")
        self.assertEqual(normalize_sex("prefer-not-to-say"), "prefer_not_to_say")
        self.assertEqual(normalize_sex("prefer not to say"), "prefer_not_to_say")
        for junk in (None, "", "m", "f", "other", "true", 1, True, [], {}):
            self.assertIsNone(normalize_sex(junk), junk)

    def test_inference_routes_only_outside_the_dead_band(self):
        from services.voice_confidence import infer_sex_from_baseline
        self.assertEqual(infer_sex_from_baseline({"f0_mean": (110.0, 12.0)}),
                         "male")
        self.assertEqual(infer_sex_from_baseline({"f0_mean": (215.0, 20.0)}),
                         "female")
        # The overlap band stays UNROUTED — sex-blind beats a coin flip,
        # because a wrong route inverts cue 1.
        for ambiguous in (145.0, 160.0, 175.0, 185.0):
            self.assertIsNone(
                infer_sex_from_baseline({"f0_mean": (ambiguous, 10.0)}),
                ambiguous)

    def test_inference_is_silent_on_junk(self):
        from services.voice_confidence import infer_sex_from_baseline
        for junk in (None, {}, {"f0_mean": None}, {"f0_mean": ()},
                     {"f0_mean": ("x", 1.0)}, {"f0_mean": (0.0, 1.0)},
                     {"f0_mean": (-40.0, 1.0)}, {"dynamic_db": (5.0, 1.0)},
                     "nope", 7):
            self.assertIsNone(infer_sex_from_baseline(junk), junk)

    def test_inference_kill_switch(self):
        from services.voice_confidence import infer_sex_from_baseline
        with patch.dict("os.environ",
                        {"VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED": "0"}):
            self.assertIsNone(infer_sex_from_baseline({"f0_mean": (110.0, 12.0)}))
        with patch.dict("os.environ",
                        {"VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED": "1"}):
            self.assertEqual(
                infer_sex_from_baseline({"f0_mean": (110.0, 12.0)}), "male")


class TestSexResolution(unittest.TestCase):

    _MALE_BASELINE = {"f0_mean": (110.0, 12.0)}

    def _db(self, stored):
        d = MagicMock()
        d.get_user_speaker_sex.return_value = stored
        return d

    def test_declared_wins_over_the_acoustics(self):
        """A woman with an unusually low voice must not be re-routed by our
        pitch heuristic once she has told us."""
        from services.voice_confidence import resolve_speaker_sex
        sex, source = resolve_speaker_sex(
            "u1", self._MALE_BASELINE, database=self._db("female"))
        self.assertEqual((sex, source), ("female", "declared"))

    def test_declining_to_answer_suppresses_inference(self):
        """THE opt-out guard. An opt-out we route around by reading the user's
        voice instead is not an opt-out — it must land on sex-blind weights."""
        from services.voice_confidence import resolve_speaker_sex
        sex, source = resolve_speaker_sex(
            "u1", self._MALE_BASELINE,
            database=self._db("prefer_not_to_say"))
        self.assertIsNone(sex)
        self.assertEqual(source, "not_stated")

    def test_no_answer_falls_back_to_the_acoustic_route(self):
        from services.voice_confidence import resolve_speaker_sex
        sex, source = resolve_speaker_sex(
            "u1", self._MALE_BASELINE, database=self._db(None))
        self.assertEqual((sex, source), ("male", "inferred"))

    def test_ambiguous_acoustics_stay_unknown(self):
        from services.voice_confidence import resolve_speaker_sex
        sex, source = resolve_speaker_sex(
            "u1", {"f0_mean": (165.0, 10.0)}, database=self._db(None))
        self.assertIsNone(sex)
        self.assertEqual(source, "unknown")

    def test_no_baseline_and_no_user_is_unknown(self):
        from services.voice_confidence import resolve_speaker_sex
        self.assertEqual(resolve_speaker_sex(None, None), (None, "unknown"))

    def test_db_failure_degrades_to_inference_not_to_nothing(self):
        """A broken lookup is not a decline. It must not be treated as one —
        otherwise a transient DB blip silently downgrades a speaker's read."""
        from services.voice_confidence import resolve_speaker_sex
        d = MagicMock()
        d.get_user_speaker_sex.side_effect = RuntimeError("boom")
        sex, source = resolve_speaker_sex("u1", self._MALE_BASELINE, database=d)
        self.assertEqual((sex, source), ("male", "inferred"))

    def test_stored_junk_is_ignored(self):
        from services.voice_confidence import resolve_speaker_sex
        sex, source = resolve_speaker_sex(
            "u1", self._MALE_BASELINE, database=self._db("banana"))
        self.assertEqual((sex, source), ("male", "inferred"))

    def test_missing_db_method_never_raises(self):
        """A pre-migration / stubbed database has no such method."""
        from services.voice_confidence import resolve_speaker_sex
        bare = object()
        self.assertEqual(
            resolve_speaker_sex("u1", None, database=bare), (None, "unknown"))


class TestTakeSexPrecedence(unittest.TestCase):
    """resolve_take_sex — the single authority on whose sex applies to a take.

    Extracted from process_lab_recording so the backfill cannot drift from the
    record path. A drift here silently re-corrupts the training corpus, which
    is the failure #290 was opened for."""

    _MALE_BASELINE = {"f0_mean": (110.0, 12.0)}
    _FEMALE_BASELINE = {"f0_mean": (215.0, 20.0)}

    def _db(self, stored):
        d = MagicMock()
        d.get_user_speaker_sex.return_value = stored
        return d

    def _resolve(self, user_id, ctx, baseline, stored=None):
        from services.voice_confidence import resolve_take_sex
        return resolve_take_sex(user_id, ctx, baseline,
                                database=self._db(stored))

    def test_a_normal_take_uses_the_account(self):
        """No context keys → unchanged behaviour, account lookup wins."""
        self.assertEqual(
            self._resolve("u1", None, self._MALE_BASELINE, stored="female"),
            ("female", "declared"))
        self.assertEqual(
            self._resolve("u1", {}, self._MALE_BASELINE, stored="female"),
            ("female", "declared"))

    def test_an_imported_voice_never_inherits_the_coach(self):
        """THE #290 bug. A woman's talk imported by a male coach must not be
        scored with his weights — cue 1 would be inverted and the result would
        still look plausible."""
        sex, source = self._resolve(
            "coach-1", {"speaker_is_account_holder": False},
            self._FEMALE_BASELINE, stored="male")
        self.assertEqual((sex, source), ("female", "inferred"))

    def test_a_declared_speaker_sex_beats_both(self):
        sex, source = self._resolve(
            "coach-1", {"speaker_sex": "female",
                        "speaker_is_account_holder": False},
            self._MALE_BASELINE, stored="male")
        self.assertEqual((sex, source), ("female", "declared"))

    def test_a_declined_speaker_is_an_opt_out_not_a_guess(self):
        sex, source = self._resolve(
            "coach-1", {"speaker_sex": "prefer_not_to_say"},
            self._MALE_BASELINE, stored="male")
        self.assertIsNone(sex)
        self.assertEqual(source, "not_stated")

    def test_junk_speaker_sex_falls_to_acoustics_not_the_account(self):
        """A context that names a speaker at all means the account holder is
        not a safe fallback, even when the value is unusable."""
        sex, source = self._resolve(
            "coach-1", {"speaker_sex": "banana"},
            self._FEMALE_BASELINE, stored="male")
        self.assertEqual((sex, source), ("female", "inferred"))

    def test_the_record_path_delegates_rather_than_reimplements(self):
        """Source-level: process_lab_recording must not carry its own copy of
        the precedence. Two copies is how the corpus gets corrupted twice."""
        with open("services/lab_recording.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("resolve_take_sex", source)
        self.assertNotIn("speaker_is_account_holder", source)


class TestSexReachesTheStampedBlob(unittest.TestCase):

    def test_read_for_piece_records_the_route_and_its_authority(self):
        from services.voice_confidence import read_for_piece
        read = read_for_piece(_with(f0_sd=2.0, dynamic_db=1.0, wpm=1.0),
                              _UNIT_BASELINE, "user", "male", "declared")
        self.assertEqual(read["sex"], "male")
        self.assertEqual(read["sex_source"], "declared")
        self.assertEqual(read["version"], "voice-confidence-v2")

    def test_unrecognized_sex_or_source_is_stamped_unknown(self):
        from services.voice_confidence import read_for_piece
        read = read_for_piece(_with(f0_sd=2.0, dynamic_db=1.0, wpm=1.0),
                              _UNIT_BASELINE, "user", "banana", "vibes")
        self.assertEqual(read["sex"], "unknown")
        self.assertEqual(read["sex_source"], "unknown")

    def test_attach_applies_one_resolved_sex_to_every_piece(self):
        """Sex is a property of the speaker, resolved once per take — not
        re-derived per moment."""
        from services.voice_confidence import attach_voice_confidence
        pieces = [{"metrics": _with(f0_sd=float(i), dynamic_db=1.0)}
                  for i in range(6)]
        attach_voice_confidence(pieces, baseline=_UNIT_BASELINE,
                                baseline_kind="user", sex="female",
                                sex_source="declared")
        for p in pieces:
            self.assertEqual(p["metrics"]["voice_confidence"]["sex"], "female")
            self.assertEqual(
                p["metrics"]["voice_confidence"]["sex_source"], "declared")

    def _stamp(self, metrics, sex):
        from services.voice_confidence import attach_voice_confidence
        pieces = [{"metrics": dict(metrics)} for _ in range(3)]
        attach_voice_confidence(pieces, baseline=_UNIT_BASELINE,
                                baseline_kind="user", sex=sex,
                                sex_source="declared")
        return pieces[0]["metrics"]["voice_confidence"]["score"]

    def test_the_flip_survives_the_whole_stamping_path(self):
        """End-to-end on the record-time entry point. A wide pitch range reads
        CONFIDENT for a woman; for a man the same clip does not.

        Note the asymmetry, which is the design and not a shortfall: cue 1 is
        the top female cue but a modestly weighted male one, so on its own it
        carries a woman clear of the neutral dead zone and leaves a man inside
        it. What must never happen is the male read going POSITIVE."""
        wide = _with(f0_sd=3.0)
        female = self._stamp(wide, "female")
        male = self._stamp(wide, "male")
        self.assertGreater(female, 0.0)
        self.assertLessEqual(male, 0.0)
        self.assertLess(male, female)

    def test_a_man_with_corroborating_cues_reads_doubtful(self):
        """Once the flipped cue has company, the male read does leave neutral —
        and lands on the opposite side from the woman's."""
        # Wide pitch range + the pattern the paper calls unconfident in men:
        # quieter dynamics, more pausing, higher pitch, slower.
        unsure_male = _with(f0_sd=2.0, dynamic_db=-1.5, pause_ratio=1.5,
                            pause_ms=1.5, f0_mean=1.0, wpm=-1.0)
        self.assertLess(self._stamp(unsure_male, "male"), -0.3)
        # The identical acoustics under the female table are NOT as damning,
        # because there the wide range is pulling the other way.
        self.assertGreater(self._stamp(unsure_male, "female"),
                           self._stamp(unsure_male, "male"))


class TestFences(unittest.TestCase):

    def test_an_inferred_sex_is_never_written_back(self):
        """The acoustic route is a WEIGHT ROUTER, not a finding about a person.
        Persisting it would turn a heuristic into a stored claim on their
        profile and would make 'prefer not to say' unrecoverable."""
        with open("services/voice_confidence.py", encoding="utf-8") as fh:
            source = fh.read()
        for banned in ("set_user_speaker_sex", "set_user_profile", "upsert"):
            self.assertNotIn(banned, source)

    def test_sex_is_not_a_surfaced_construct(self):
        """AC-9 / CONSTRUCT. The sex term selects weights; it must never become
        a user-facing label, badge, or copy string in this module."""
        with open("services/voice_confidence.py", encoding="utf-8") as fh:
            source = fh.read()
        for banned in ("jsonify", "bubble", "suggested_action", "headline"):
            self.assertNotIn(banned, source)


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
