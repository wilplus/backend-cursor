"""willab — FORCED ALIGNMENT of a take onto the known script (founder
2026-08-03).

The pins:
  * content beats count — a speaker who dwells on one section maps
    correctly where the proportional split provably bleeds;
  * ASR noise survives via anchors + Needleman–Wunsch gap fill and the
    near-match prefix rule;
  * off-script takes are REFUSED (low coverage → fallback), never
    fabricated;
  * off-script sentences inside an on-script take ride their block's
    contiguous segment (the whole-segment contract — an accept never
    silently drops words);
  * assignments are monotone (reading order never goes backward);
  * flag OFF keeps the proportional split byte-for-byte.

Run: python3 -m unittest test_take_alignment
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.take_alignment import (
    _nw_gap,
    align_words,
    map_take_to_blocks,
)


def _block(key, *texts):
    return {
        "arc_id": "a1", "block_key": key, "active": True,
        "status": "settled",
        "incumbent_take_session_id": "t1",
        "incumbent_take_index": 1,
        "incumbent_pieces": [{"snippet_id": f"b{key}-{i}", "text": t}
                             for i, t in enumerate(texts)],
    }


def _piece(pid, text):
    return {"snippet_id": pid, "text": text}


class NwGapTests(unittest.TestCase):
    def test_exact_and_near_matches_pair_up(self):
        pairs = _nw_gap(["we", "deployed", "kubernetis", "today"],
                        ["we", "deployed", "kubernetes", "yesterday"])
        self.assertIn((0, 0), pairs)
        self.assertIn((1, 1), pairs)
        self.assertIn((2, 2), pairs)          # near match by prefix
        self.assertNotIn((3, 3), pairs)       # today != yesterday

    def test_oversized_gap_yields_nothing(self):
        a = [f"w{i}" for i in range(300)]
        self.assertEqual(_nw_gap(a, a), [])   # 300*300 > cap

    def test_empty_sides(self):
        self.assertEqual(_nw_gap([], ["a"]), [])
        self.assertEqual(_nw_gap(["a"], []), [])


class AlignWordsTests(unittest.TestCase):
    def test_anchors_plus_gap_fill(self):
        take = "the plan is simpel we ship on friday".split()
        script = "the plan is simple we ship on friday".split()
        pairs = align_words(take, script)
        # every word pairs — 'simpel'/'simple' via the NW near rule
        self.assertEqual(len(pairs), 8)
        self.assertEqual([a for a, _ in pairs], list(range(8)))

    def test_monotone(self):
        take = "alpha beta gamma alpha beta".split()
        script = "alpha beta gamma delta alpha beta".split()
        pairs = align_words(take, script)
        for (a1, b1), (a2, b2) in zip(pairs, pairs[1:]):
            self.assertLess(a1, a2)
            self.assertLess(b1, b2)


class MappingTests(unittest.TestCase):
    BLOCKS = [
        _block(0, "our hook is the mobile demo everyone remembers"),
        _block(10, "the context is the enterprise pilot from march"),
        _block(20, "the core message is that retention doubled and "
                   "churn fell and the pipeline is full and growing"),
    ]

    def test_content_beats_count(self):
        """The speaker dwells on the last block: 2 of 4 pieces belong to
        it. The proportional split would hand piece 2 to block 0 and
        piece 3 to block 10 — alignment maps by what was SAID."""
        pieces = [
            _piece("p0", "our hook is the mobile demo everyone remembers"),
            _piece("p1", "the context is the enterprise pilot from march"),
            _piece("p2", "the core message is that retention doubled"),
            _piece("p3", "and churn fell and the pipeline is full "
                         "and growing"),
        ]
        mapping, info = map_take_to_blocks(pieces, self.BLOCKS)
        self.assertIsNotNone(mapping)
        self.assertFalse(info["off_script"])
        self.assertEqual(
            {k: [p["snippet_id"] for p in v] for k, v in mapping.items()},
            {0: ["p0"], 10: ["p1"], 20: ["p2", "p3"]})

    def test_asr_noise_still_maps(self):
        pieces = [
            _piece("p0", "our hook is the mobil demo everyone remembers"),
            _piece("p1", "the contexd is the enterprize pilot from march"),
            _piece("p2", "the core message is that retension doubled and "
                         "churn fell and the pipeline is full and growing"),
        ]
        mapping, info = map_take_to_blocks(pieces, self.BLOCKS)
        self.assertIsNotNone(mapping)
        self.assertEqual(sorted(mapping), [0, 10, 20])
        self.assertEqual([p["snippet_id"] for p in mapping[20]], ["p2"])

    def test_off_script_take_is_refused(self):
        pieces = [
            _piece("p0", "completely different words about skiing"),
            _piece("p1", "nothing from any script here at all today"),
        ]
        mapping, info = map_take_to_blocks(pieces, self.BLOCKS)
        self.assertIsNone(mapping)
        self.assertTrue(info["off_script"])

    def test_new_material_rides_its_blocks_segment(self):
        """An off-script sentence spoken INSIDE block 10's stretch stays
        in block 10's contiguous segment — nothing is dropped."""
        pieces = [
            _piece("p0", "our hook is the mobile demo everyone remembers"),
            _piece("p1", "the context is the enterprise pilot from march"),
            _piece("p2", "also a brand new anecdote nobody scripted"),
            _piece("p3", "the core message is that retention doubled and "
                         "churn fell and the pipeline is full and growing"),
        ]
        mapping, info = map_take_to_blocks(pieces, self.BLOCKS)
        self.assertIsNotNone(mapping)
        all_ids = [p["snippet_id"] for seg in mapping.values() for p in seg]
        self.assertEqual(sorted(all_ids), ["p0", "p1", "p2", "p3"])
        self.assertEqual([p["snippet_id"] for p in mapping[10]],
                         ["p1", "p2"])
        self.assertEqual(info["unvoted_pieces"], 1)

    def test_leading_unvoted_pieces_join_the_first_block(self):
        pieces = [
            _piece("p0", "unscripted throat clearing first"),
            _piece("p1", "our hook is the mobile demo everyone remembers"),
            _piece("p2", "the context is the enterprise pilot from march"),
            _piece("p3", "the core message is that retention doubled and "
                         "churn fell and the pipeline is full and growing"),
        ]
        mapping, _ = map_take_to_blocks(pieces, self.BLOCKS)
        self.assertIsNotNone(mapping)
        self.assertEqual([p["snippet_id"] for p in mapping[0]],
                         ["p0", "p1"])

    def test_monotone_clamp_never_goes_backward(self):
        """A piece echoing block 0's words AFTER block 20 started stays
        clamped forward — a segment can never be non-contiguous."""
        pieces = [
            _piece("p0", "our hook is the mobile demo everyone remembers"),
            _piece("p1", "the context is the enterprise pilot from march"),
            _piece("p2", "the core message is that retention doubled and "
                         "churn fell and the pipeline is full and growing"),
            _piece("p3", "our hook is the mobile demo"),   # echo of block 0
        ]
        mapping, _ = map_take_to_blocks(pieces, self.BLOCKS)
        self.assertIsNotNone(mapping)
        self.assertEqual([p["snippet_id"] for p in mapping[20]],
                         ["p2", "p3"])

    def test_candidate_and_inactive_blocks_are_not_targets(self):
        blocks = list(self.BLOCKS) + [
            dict(_block(30, "candidate material"), status="candidate",
                 active=False),
        ]
        pieces = [
            _piece("p0", "our hook is the mobile demo everyone remembers"),
            _piece("p1", "the context is the enterprise pilot from march"),
            _piece("p2", "the core message is that retention doubled and "
                         "churn fell and the pipeline is full and growing"),
        ]
        mapping, _ = map_take_to_blocks(pieces, blocks)
        self.assertIsNotNone(mapping)
        self.assertNotIn(30, mapping)

    def test_empty_inputs_refuse(self):
        self.assertIsNone(map_take_to_blocks([], self.BLOCKS)[0])
        self.assertIsNone(map_take_to_blocks(
            [_piece("p0", "words")], [])[0])


class SegmentIntegrationTests(unittest.TestCase):
    """segment_take_for_blocks: flag ON uses alignment; flag OFF (and
    the off-script fallback) keeps the proportional split."""

    BLOCKS = MappingTests.BLOCKS

    PIECES = [
        _piece("p0", "our hook is the mobile demo everyone remembers"),
        _piece("p1", "the context is the enterprise pilot from march"),
        _piece("p2", "the core message is that retention doubled"),
        _piece("p3", "and churn fell and the pipeline is full "
                     "and growing"),
    ]

    def test_flag_on_maps_by_content(self):
        from services.master_document import segment_take_for_blocks
        with patch.dict(os.environ, {"TAKE_ALIGNMENT_ENABLED": "1"}):
            mapping, extras = segment_take_for_blocks(
                self.PIECES, self.BLOCKS, {})
        self.assertEqual(extras, [])
        self.assertEqual(
            {k: [p["snippet_id"] for p in v] for k, v in mapping.items()},
            {0: ["p0"], 10: ["p1"], 20: ["p2", "p3"]})

    def test_flag_off_keeps_proportional(self):
        from services.master_document import segment_take_for_blocks
        with patch.dict(os.environ, {"TAKE_ALIGNMENT_ENABLED": "0"}):
            mapping, extras = segment_take_for_blocks(
                self.PIECES, self.BLOCKS, {})
        # count split: 4 pieces over 3 blocks → 2/1/1 — the known bleed
        self.assertEqual(
            {k: [p["snippet_id"] for p in v] for k, v in mapping.items()},
            {0: ["p0", "p1"], 10: ["p2"], 20: ["p3"]})

    def test_flag_on_off_script_falls_back_to_proportional(self):
        from services.master_document import segment_take_for_blocks
        off = [
            _piece("p0", "completely different words about skiing"),
            _piece("p1", "nothing from any script here at all"),
            _piece("p2", "still nothing related whatsoever"),
        ]
        with patch.dict(os.environ, {"TAKE_ALIGNMENT_ENABLED": "1"}):
            mapping, _ = segment_take_for_blocks(off, self.BLOCKS, {})
        self.assertEqual(
            {k: [p["snippet_id"] for p in v] for k, v in mapping.items()},
            {0: ["p0"], 10: ["p1"], 20: ["p2"]})

    def test_decked_takes_are_untouched_by_the_flag(self):
        """Slide-exact mapping stays the decked truth — alignment never
        runs when both sides carry slide identity."""
        from services.master_document import segment_take_for_blocks
        blocks = [
            dict(_block(0, "slide one words"), slide_index=0),
            dict(_block(10, "slide two words"), slide_index=1),
        ]
        snips = {
            "n0": {"id": "n0", "metrics": {"piece": {"slide_index": 1}}},
        }
        pieces = [_piece("n0", "retake of slide two")]
        with patch.dict(os.environ, {"TAKE_ALIGNMENT_ENABLED": "1"}):
            mapping, extras = segment_take_for_blocks(pieces, blocks, snips)
        self.assertEqual(
            {k: [p["snippet_id"] for p in v] for k, v in mapping.items()},
            {10: ["n0"]})
        self.assertEqual(extras, [])


if __name__ == "__main__":
    unittest.main()
