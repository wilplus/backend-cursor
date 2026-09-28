"""What ``current_take_confident_voice_candidate`` picks, pinned before its
split into named stages (audit W1, 2026-09-28).

``tests/test_take_review.py`` covers the product cases. These pin the
ranking and the edges that had no test: the early refusals, a shared
phrase, cue evidence, a wordless region, a missing Take id, and the exact
row and evidence piece the Manager receives.
"""
from __future__ import annotations

import unittest

from services.take_feedback_candidates import (
    current_take_confident_voice_candidate as pick,
)

P1 = "We started small and listened."
P2 = "Then we shipped it fast."
TEXT = P1 + "\n\n" + P2
CANONICAL = [
    {"snippet_id": "old-1", "take_session_id": "take-1", "slide_index": 0,
     "start": 0, "end": len(P1), "text": P1},
    {"snippet_id": "old-2", "take_session_id": "take-1", "slide_index": 1,
     "start": len(P1) + 2, "end": len(TEXT), "text": P2},
]


def _piece(sid, slide=1, text="Completely different wording.", **extra):
    return {"snippet_id": sid, "take_session_id": "take-2",
            "slide_index": slide, "text": text, **extra}


def _take(*pieces, **extra):
    return {"take_session_id": "take-2", "pieces": list(pieces), **extra}


def _emphasize(trigger="confidence_review", **extra):
    return {"kind": "emphasize", "trigger": trigger, "why": trigger, **extra}


class RefusalsTests(unittest.TestCase):
    def test_nothing_to_place_is_none_none(self):
        take = _take(_piece("a"))
        self.assertEqual(pick("", canonical_pieces=CANONICAL,
                              take_document=take, suggestions={}),
                         (None, None))
        self.assertEqual(pick(TEXT, canonical_pieces=CANONICAL,
                              take_document=_take(), suggestions={}),
                         (None, None))
        self.assertEqual(pick(TEXT, canonical_pieces=[],
                              take_document=take, suggestions={}),
                         (None, None))
        self.assertEqual(pick(None, canonical_pieces=None,
                              take_document=None, suggestions=None),
                         (None, None))

    def test_an_excluded_detector_snippet_is_not_reoffered_as_a_fallback(self):
        take = _take(_piece("a"), _piece("b"))
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions={"a": _emphasize("confident")},
                         excluded_snippet_ids=["a"])
        self.assertEqual(change["snippet_id"], "b")
        self.assertTrue(change["_manager_evidence"]["fallback"])

    def test_no_take_id_anywhere_skips_the_piece(self):
        orphan = _piece("a")
        orphan["take_session_id"] = None
        take = {"pieces": [orphan, _piece("b")]}
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions={"a": _emphasize("confident")})
        self.assertEqual(change["snippet_id"], "b")
        self.assertEqual(pick(TEXT, canonical_pieces=CANONICAL,
                              take_document={"pieces": [orphan]},
                              suggestions={}),
                         (None, None))

    def test_the_document_take_id_fills_in_for_the_piece(self):
        piece = _piece("a")
        del piece["take_session_id"]
        change, evidence = pick(TEXT, canonical_pieces=CANONICAL,
                                take_document=_take(piece), suggestions={})
        self.assertEqual(change["take_session_id"], "take-2")
        self.assertEqual(evidence["take_session_id"], "take-2")

    def test_regions_that_are_malformed_or_hold_no_word_are_skipped(self):
        text = "... " + P2
        canonical = [
            {"slide_index": 1, "start": 0, "end": 3},            # no word
            {"slide_index": 1, "start": 5, "end": 4},            # inverted
            {"slide_index": 1, "start": True, "end": 9},         # bool
            {"slide_index": 1, "start": 4, "end": len(text) + 1},  # too long
        ]
        self.assertEqual(pick(text, canonical_pieces=canonical,
                              take_document=_take(_piece("a")),
                              suggestions={}),
                         (None, None))
        canonical.append({"slide_index": 1, "start": 4, "end": len(text)})
        change, evidence = pick(text, canonical_pieces=canonical,
                                take_document=_take(_piece("a")),
                                suggestions={})
        self.assertEqual(change["quote"], "Then")
        self.assertEqual((evidence["start"], evidence["end"]), (4, 8))


class RankingTests(unittest.TestCase):
    def test_confident_beats_review_beats_fallback_whatever_the_order(self):
        take = _take(_piece("fallback"), _piece("review"), _piece("sure"))
        suggestions = {"review": _emphasize(),
                       "sure": _emphasize("confident")}
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions=suggestions)
        self.assertEqual(change["snippet_id"], "sure")
        self.assertEqual(change["_manager_evidence"],
                         {"detector_rank": 2, "anchor_score": 1,
                          "fallback": False})
        del suggestions["sure"]
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions=suggestions)
        self.assertEqual(change["snippet_id"], "review")
        self.assertEqual(change["_manager_evidence"]["detector_rank"], 1)

    def test_a_non_emphasize_row_is_a_neutral_fallback_not_a_detector(self):
        take = _take(_piece("a"))
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions={"a": {"kind": "replace",
                                            "trigger": "confident"}})
        self.assertEqual(change["why"], "Possible confident moment for review.")
        self.assertEqual(change["_manager_evidence"],
                         {"detector_rank": 0, "anchor_score": 1,
                          "fallback": True})

    def test_more_known_cues_win_at_the_same_detector_rank(self):
        take = _take(_piece("one"), _piece("two"))
        suggestions = {
            "one": _emphasize("confident", cue_keys=["kept_moving"]),
            "two": _emphasize("confident", cue_keys=[
                "full_volume", "not-a-cue", 7, "landed_ending"]),
        }
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions=suggestions)
        self.assertEqual(change["snippet_id"], "two")
        self.assertEqual(change["cue_keys"], ["full_volume", "landed_ending"])
        self.assertEqual(change["_manager_evidence"]["cue_count"], 2)

    def test_the_picked_quote_beats_a_shared_phrase_beats_a_route(self):
        take = _take(
            _piece("route"),
            _piece("shared", text="and so we shipped it quickly"),
            _piece("quoted"),
        )
        suggestions = {sid: _emphasize() for sid in ("route", "shared")}
        suggestions["quoted"] = _emphasize(emphasis_quote=" IT FAST ")
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions=suggestions)
        self.assertEqual((change["snippet_id"], change["quote"],
                          change["anchor_role"]),
                         ("quoted", "it fast", "spoken_phrase"))
        self.assertEqual(change["_manager_evidence"]["anchor_score"], 3)
        del suggestions["quoted"]
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions=suggestions)
        self.assertEqual((change["snippet_id"], change["quote"],
                          change["anchor_role"]),
                         ("shared", "we shipped it", "spoken_phrase"))
        self.assertEqual(change["_manager_evidence"]["anchor_score"], 2)

    def test_document_order_breaks_a_full_tie(self):
        take = _take(_piece("later-id"), _piece("earlier-id"))
        change, _ = pick(TEXT, canonical_pieces=CANONICAL, take_document=take,
                         suggestions={})
        self.assertEqual(change["snippet_id"], "later-id")

    def test_the_best_region_on_the_slide_is_the_earliest_best_anchor(self):
        text = "Nothing here. Then we shipped it fast."
        canonical = [
            {"slide_index": 1, "start": 0, "end": 13, "text": "a"},
            {"slide_index": 1, "start": 14, "end": len(text), "text": "b"},
        ]
        take = _take(_piece("a"))
        change, evidence = pick(
            text, canonical_pieces=canonical, take_document=take,
            suggestions={"a": _emphasize(emphasis_quote="shipped")})
        self.assertEqual(change["quote"], "shipped")
        self.assertEqual(evidence["text"], "shipped")
        self.assertEqual(pick(text, canonical_pieces=canonical,
                              take_document=take, suggestions={})[0]["quote"],
                         "Nothing")


class ExactOutputTests(unittest.TestCase):
    def test_the_row_and_the_evidence_piece(self):
        take = _take(_piece("new-2", extra="kept-on-piece"))
        region = dict(CANONICAL[1], paragraph_id="p-2")
        change, evidence = pick(
            TEXT, canonical_pieces=[CANONICAL[0], region], take_document=take,
            suggestions={"new-2": _emphasize(
                "confident", emphasis_quote="shipped it",
                cue_keys=["opened_strong"])})
        start = TEXT.index("shipped it")
        self.assertEqual(change, {
            "id": "confident-voice:new-2",
            "snippet_id": "new-2",
            "take_session_id": "take-2",
            "kind": "bold",
            "source": "confident_voice",
            "span": {"start": start, "end": start + 10},
            "quote": "shipped it",
            "why_key": "confident_voice",
            "why": "confident",
            "anchor_role": "spoken_phrase",
            "_manager_evidence": {"detector_rank": 2, "anchor_score": 3,
                                  "fallback": False, "cue_count": 1},
            "cue_keys": ["opened_strong"],
        })
        self.assertEqual(evidence, {
            "snippet_id": "new-2",
            "take_session_id": "take-2",
            "slide_index": 1,
            "start": start,
            "end": start + 10,
            "text": "shipped it",
            "paragraph_id": "p-2",
        })


if __name__ == "__main__":
    unittest.main()
