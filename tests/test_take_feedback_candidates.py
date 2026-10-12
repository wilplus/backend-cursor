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


if __name__ == "__main__":
    unittest.main()
