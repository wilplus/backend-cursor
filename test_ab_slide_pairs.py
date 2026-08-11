"""BLINDED A/B SLIDE PAIRS (founder 2026-08-11) — the corpus that unblocks
piece (b) of the north star.

The audit found best-text-per-slide ranking blocked twice, and neither block
is code: power_score's DELIVERY term is ranking-inert until the composite is
anchored against blinded human ratings, and line-level cross-take selection
is disabled until a fuzzy-alignment spike can run on real multi-take arcs.
One coach act produces both.

THE BLINDING IS THE INSTRUMENT, so it is what these tests are mostly about.
A rater who can tell which take is later is rating a story about improvement
rather than a delivery, and a corpus collected that way is worse than none —
it would anchor the composite to recency and nobody could tell from the rows.

Run: python3 -m unittest test_ab_slide_pairs
"""
from __future__ import annotations

import unittest

from services.ab_slide_pairs import (
    build_pairs, decode_pair_id, left_is_lo, pair_id, resolve_verdict,
)

S1 = "aaaa1111-aaaa-1111-aaaa-111111111111"
S2 = "bbbb2222-bbbb-2222-bbbb-222222222222"
S3 = "cccc3333-cccc-3333-cccc-333333333333"

SLIDES = [{"title": "Intro", "body": "x"},
          {"title": "Body", "body": "y"},
          {"title": "Close", "body": "z"}]


def _take(sid, texts, audio="https://a/x.webm"):
    """texts: {slide_index: transcript}."""
    return {
        "session_id": sid,
        "audio_ref": audio,
        "slide_transcripts": [
            {"index": i, "transcript": t,
             "start_offset_ms": 1000 * i, "duration_ms": 5000}
            for i, t in texts.items()
        ],
    }


FULL_A = _take(S1, {0: "we started small and it worked",
                    1: "the numbers came in strong",
                    2: "so here is what i am asking"})
FULL_B = _take(S2, {0: "we began in a garage with nothing",
                    1: "and the numbers were remarkable",
                    2: "so this is the ask"})


class BlindingTests(unittest.TestCase):
    """The property the whole instrument rests on."""

    def test_a_side_carries_NOTHING_that_says_which_take_it_is(self):
        pairs = build_pairs([FULL_A, FULL_B], SLIDES)
        self.assertTrue(pairs)
        for p in pairs:
            for side in (p["left"], p["right"]):
                self.assertEqual(
                    set(side),
                    {"transcript", "audio_ref", "start_offset_ms",
                     "duration_ms"},
                )
                # Spelled out, because this is the assertion that matters:
                # no id, no take index, no timestamp to order them by.
                self.assertNotIn("session_id", side)
                self.assertNotIn("take_index", side)
                self.assertNotIn("created_at", side)

    def test_the_side_a_take_lands_on_is_not_its_take_order(self):
        # If the earlier take always showed left, position bias and recency
        # bias would be the same axis and neither could be measured. Across
        # a deck the assignment must vary.
        pairs = build_pairs([FULL_A, FULL_B], SLIDES)
        left_texts = [p["left"]["transcript"] for p in pairs]
        from_a = sum(1 for t in left_texts
                     if t in FULL_A["slide_transcripts"][0]["transcript"]
                     or any(t == s["transcript"]
                            for s in FULL_A["slide_transcripts"]))
        self.assertGreater(len(pairs), 1)
        # Not all from one take (the hash decides, not the order).
        self.assertNotEqual(from_a, len(pairs))

    def test_the_layout_is_STABLE_for_a_given_pair(self):
        # A coach re-opening a pair must not see it flip under their hand —
        # that would make the second look different from the first for a
        # reason that has nothing to do with the delivery.
        first = build_pairs([FULL_A, FULL_B], SLIDES)
        again = build_pairs([FULL_B, FULL_A], SLIDES)  # caller order swapped
        self.assertEqual([p["pair_id"] for p in first],
                         [p["pair_id"] for p in again])
        self.assertEqual([p["left"]["transcript"] for p in first],
                         [p["left"]["transcript"] for p in again])


class PairIdentityTests(unittest.TestCase):
    def test_the_id_is_canonical_so_one_comparison_is_one_pair(self):
        # Same two takes, same slide, either caller order → one id. Without
        # this the corpus would double-count a single judgment.
        self.assertEqual(pair_id(1, S1, S2), pair_id(1, S2, S1))
        self.assertNotEqual(pair_id(1, S1, S2), pair_id(2, S1, S2))

    def test_it_round_trips(self):
        tok = pair_id(2, S2, S1)
        self.assertEqual(decode_pair_id(tok), (2, min(S1, S2), max(S1, S2)))

    def test_garbage_decodes_to_None_rather_than_a_guess(self):
        for bad in ("", None, "!!!!", "zzzz", 7):
            self.assertIsNone(decode_pair_id(bad))


class PairBuildingTests(unittest.TestCase):
    def test_three_takes_give_three_pairs_per_slide(self):
        third = _take(S3, {0: "it started in a small room",
                           1: "the numbers told the story",
                           2: "here is the one ask"})
        pairs = build_pairs([FULL_A, FULL_B, third], SLIDES)
        self.assertEqual(len(pairs), 9)          # 3 slides × 3 combinations
        self.assertEqual(len({p["pair_id"] for p in pairs}), 9)

    def test_a_slide_only_one_take_spoke_on_yields_nothing(self):
        quiet = _take(S2, {0: "we began in a garage with nothing"})
        pairs = build_pairs([FULL_A, quiet], SLIDES)
        self.assertEqual([p["slide_index"] for p in pairs], [0])

    def test_a_near_silent_side_is_not_a_comparison(self):
        # Judging "um" against a real delivery collects a verdict about
        # silence, not about delivery.
        thin = _take(S2, {0: "um", 1: "and the numbers were remarkable"})
        pairs = build_pairs([FULL_A, thin], SLIDES)
        self.assertEqual([p["slide_index"] for p in pairs], [1])

    def test_one_take_or_no_deck_gives_no_queue(self):
        self.assertEqual(build_pairs([FULL_A], SLIDES), [])
        self.assertEqual(build_pairs([FULL_A, FULL_B], []), [])
        self.assertEqual(build_pairs(None, SLIDES), [])

    def test_the_slide_title_rides_along_but_no_take_context(self):
        # What the AUDIENCE saw is not a cue about which take this is, so the
        # coach may have it; anything take-shaped may not.
        p = build_pairs([FULL_A, FULL_B], SLIDES)[0]
        self.assertEqual(p["slide_title"], "Intro")
        self.assertEqual(set(p),
                         {"pair_id", "slide_index", "slide_title",
                          "left", "right"})


class ResolveVerdictTests(unittest.TestCase):
    def test_a_blinded_side_resolves_to_the_real_session(self):
        tok = pair_id(1, S1, S2)
        lo, hi = sorted([S1, S2])
        left = lo if left_is_lo(tok) else hi
        out = resolve_verdict(tok, "left")
        self.assertEqual(out["winner_session_id"], left)
        self.assertEqual(out["slide_index"], 1)

    def test_the_sides_are_recorded_AS_SHOWN_so_position_bias_is_measurable(self):
        tok = pair_id(0, S1, S2)
        out = resolve_verdict(tok, "right")
        self.assertNotEqual(out["session_left"], out["session_right"])
        self.assertEqual(out["winner_session_id"], out["session_right"])
        # Collapsing to winner/loser would make "did left win more often
        # than chance" unanswerable forever.
        self.assertIn("session_left", out)

    def test_a_tie_is_a_verdict_with_no_winner(self):
        out = resolve_verdict(pair_id(0, S1, S2), "tie")
        self.assertEqual(out["verdict"], "tie")
        self.assertIsNone(out["winner_session_id"])

    def test_an_unreadable_judgment_is_DROPPED_never_guessed(self):
        self.assertIsNone(resolve_verdict(pair_id(0, S1, S2), "maybe"))
        self.assertIsNone(resolve_verdict("garbage!!", "left"))
        self.assertIsNone(resolve_verdict(None, "left"))


if __name__ == "__main__":
    unittest.main()
