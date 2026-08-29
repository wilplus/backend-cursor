"""willab — WHAT THE VOICE DID (founder 2026-08-15).

"for the underlining use the verbal and vocal cues of what the user said to
determine that it was confident … not just random", and "in the justification
of the positive feedback explain using the vocal and verbal cues."

The composite in services/voice_confidence.py sums seven cues into one number.
These tests pin the two things it discards and this module recovers: WHICH
cues carried a moment, and WHERE inside it the delivery landed.

Run: python3 -m unittest test_delivery_cues
"""
from __future__ import annotations

import unittest

from services.delivery_cues import (
    CLOSING, CUE_KEYS, OPENING, accent_region, cue_keys_for_piece,
    is_impeccable,
)

# A baseline is {feature: (mean, sd)} — the speaker's OWN norm. Unit sd
# throughout so a feature value reads directly as its own z.
BASE = {
    "f0_sd": (10.0, 1.0),
    "dynamic_db": (10.0, 1.0),
    "pause_ratio": (10.0, 1.0),
    "pause_ms": (10.0, 1.0),
    "f0_mean": (10.0, 1.0),
    "wpm": (10.0, 1.0),
    "f0_mid_end_delta": (10.0, 1.0),
    "intensity_envelope": (10.0, 1.0),
}


def piece(**z) -> dict:
    """A metrics blob whose every named feature sits `z` sd from the norm."""
    return {k: 10.0 + v for k, v in z.items()}


class VocabularyTests(unittest.TestCase):
    def test_every_key_is_a_key_not_a_sentence(self):
        # The FE holds the copy (LIVE LOOP); a sentence escaping from here
        # would be unsigned-off product copy.
        for k in CUE_KEYS:
            self.assertRegex(k, r"^[a-z][a-z_]+$")
            self.assertLess(len(k), 24)

    def test_the_vocabulary_is_closed_and_stable(self):
        self.assertEqual(CUE_KEYS, (
            "full_volume", "kept_moving", "landed_ending",
            "no_hesitation", "opened_strong", "settled_pitch", "wide_range",
        ))


class CueReadingTests(unittest.TestCase):
    def test_it_names_the_cues_that_actually_carried_the_moment(self):
        keys = cue_keys_for_piece(
            piece(f0_sd=+2.0, dynamic_db=+1.5, wpm=+0.1), BASE)
        self.assertIn("wide_range", keys)
        self.assertIn("full_volume", keys)
        self.assertNotIn("kept_moving", keys)   # +0.1 is noise, not a cue

    def test_strongest_first(self):
        keys = cue_keys_for_piece(
            piece(dynamic_db=+1.0, f0_sd=+3.0), BASE)
        self.assertEqual(keys[0], "wide_range")

    def test_at_most_three_cues(self):
        # Seven cues in a line is a printout, and a printout breaches AC-9 in
        # spirit while obeying its letter.
        keys = cue_keys_for_piece(
            piece(f0_sd=+2.0, dynamic_db=+2.0, wpm=+2.0, f0_mean=-2.0,
                  pause_ratio=-2.0, pause_ms=-2.0, f0_mid_end_delta=+2.0,
                  intensity_envelope=-2.0), BASE)
        self.assertEqual(len(keys), 3)

    def test_a_cue_pointing_the_WRONG_way_is_never_named(self):
        keys = cue_keys_for_piece(piece(f0_sd=-3.0), BASE)
        self.assertNotIn("wide_range", keys)

    def test_every_speaker_uses_the_same_pitch_range_direction(self):
        wide = piece(f0_sd=+3.0)
        narrow = piece(f0_sd=-3.0)
        self.assertIn("wide_range", cue_keys_for_piece(wide, BASE))
        self.assertNotIn("wide_range", cue_keys_for_piece(narrow, BASE))

    def test_pausing_reads_as_the_absence_of_hesitation(self):
        keys = cue_keys_for_piece(
            piece(pause_ratio=-2.0, pause_ms=-2.0), BASE)
        self.assertEqual(keys, ["no_hesitation"])

    def test_no_baseline_no_cues(self):
        # A first take has no norm to be measured against. Silence is the
        # honest answer, not a default set.
        self.assertEqual(cue_keys_for_piece(piece(f0_sd=+3.0), None), [])
        self.assertEqual(cue_keys_for_piece(piece(f0_sd=+3.0), {}), [])

    def test_junk_never_raises(self):
        for bad in (None, "", 42, [], {"f0_sd": "loud"}):
            self.assertEqual(cue_keys_for_piece(bad, BASE), [])


class AccentRegionTests(unittest.TestCase):
    """The one WITHIN-moment signal the seven cues actually carry."""

    def test_front_loaded_energy_points_at_the_opening(self):
        # intensity_envelope BELOW the norm = the energy fades from the start,
        # which is the confident direction and means they led with it.
        self.assertEqual(
            accent_region(piece(intensity_envelope=-2.0), BASE), OPENING)

    def test_a_landed_ending_points_at_the_closing(self):
        # f0_mid_end_delta ABOVE the norm = the ending came DOWN rather than
        # drifting up.
        self.assertEqual(
            accent_region(piece(f0_mid_end_delta=+2.0), BASE), CLOSING)

    def test_the_stronger_of_the_two_wins(self):
        self.assertEqual(
            accent_region(piece(intensity_envelope=-3.0,
                                f0_mid_end_delta=+1.0), BASE), OPENING)
        self.assertEqual(
            accent_region(piece(intensity_envelope=-1.0,
                                f0_mid_end_delta=+3.0), BASE), CLOSING)

    def test_a_NEAR_TIE_says_nothing(self):
        # A strong open AND a landed close is two true things. Breaking the
        # tie on a rounding difference is exactly the "random" the founder
        # objected to.
        self.assertIsNone(
            accent_region(piece(intensity_envelope=-2.0,
                                f0_mid_end_delta=+2.0), BASE))

    def test_weak_evidence_says_nothing(self):
        self.assertIsNone(
            accent_region(piece(intensity_envelope=-0.2), BASE))

    def test_the_wrong_direction_is_not_evidence(self):
        # Energy BUILDING is the unconfident direction — it is not a claim
        # that the closing landed.
        self.assertIsNone(
            accent_region(piece(intensity_envelope=+3.0), BASE))

    def test_no_baseline_no_region(self):
        self.assertIsNone(accent_region(piece(intensity_envelope=-3.0), None))

    def test_junk_never_raises(self):
        for bad in (None, "", 42, []):
            self.assertIsNone(accent_region(bad, BASE))


class ImpeccableTests(unittest.TestCase):
    """"If the delivery was impeccable, just give them the feedback in the
    praise lane" — so the bar has to be high enough that the praise means
    something the tenth time."""

    STRONG = dict(f0_sd=+2.0, dynamic_db=+2.0, pause_ratio=-2.0)

    def test_two_cues_and_a_confident_read(self):
        self.assertTrue(is_impeccable(
            piece(**self.STRONG), BASE, confidence_score=0.8))

    def test_ONE_cue_is_a_coincidence_not_a_finding(self):
        self.assertFalse(is_impeccable(
            piece(f0_sd=+3.0), BASE, confidence_score=0.9))

    def test_a_BORDERLINE_read_is_not_impeccable(self):
        # Squeaking past the neutral dead zone (0.25) is not "impeccable",
        # and saying so devalues every later praise line.
        self.assertFalse(is_impeccable(
            piece(**self.STRONG), BASE, confidence_score=0.3))

    def test_an_absent_score_falls_back_to_the_cues_alone(self):
        self.assertTrue(is_impeccable(piece(**self.STRONG), BASE))
        self.assertFalse(is_impeccable(piece(f0_sd=+3.0), BASE))

    def test_a_junk_score_is_not_a_pass(self):
        for bad in ("high", [], {}):
            self.assertFalse(is_impeccable(
                piece(**self.STRONG), BASE, confidence_score=bad))

    def test_no_baseline_no_praise(self):
        self.assertFalse(is_impeccable(piece(**self.STRONG), None))


class OneDefinitionTests(unittest.TestCase):
    """The cues are re-read through voice_confidence's OWN tables. A second
    copy would drift, and a drifted copy would praise a speaker for something
    the ranking scored against them."""

    def test_it_imports_the_weight_tables_rather_than_restating_them(self):
        import inspect

        from services import delivery_cues as dc
        src = inspect.getsource(dc)
        self.assertIn("from services.voice_confidence import", src)
        self.assertIn("confidence_cues", src)
        # No weight TABLE of its own — those live in one place, deliberately.
        self.assertNotIn("speaker_sex", src)
        for weight in ("0.18", "0.20", "0.24", "0.13", "0.09"):
            self.assertNotIn(weight, src, f"weight {weight} restated here")

    def test_no_number_can_leave_this_module(self):
        # AC-9: everything crossing the boundary is a key or a region word.
        keys = cue_keys_for_piece(piece(f0_sd=+3.0, dynamic_db=+2.0), BASE)
        self.assertTrue(all(isinstance(k, str) for k in keys))
        self.assertIn(accent_region(piece(intensity_envelope=-3.0), BASE),
                      (OPENING, CLOSING, None))


if __name__ == "__main__":
    unittest.main()
