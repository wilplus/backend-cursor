"""The acoustic swap lane, stage 4 — the orchestration (founder 2026-08-13).

Run: python3 -m unittest test_swap_detector
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import swap_detector as sd


PARTS = [
    {"id": "p0", "ord": 0, "text": "First slide words go here.", "locked": False},
    {"id": "p1", "ord": 1, "text": "Second slide words go here.", "locked": True},
    {"id": "p2", "ord": 2, "text": "Third slide words go here.", "locked": True},
]


def _piece(snippet_id, start, end, text):
    return {"snippet_id": snippet_id, "start": start, "end": end, "text": text}


class LockedPartTests(unittest.TestCase):
    def test_only_locked_parts_are_eligible(self):
        self.assertEqual(sd._locked_part_ids(PARTS), {"p1", "p2"})

    def test_junk_is_survivable(self):
        for bad in (None, [], [None, 42, {}], {"nope": 1}):
            self.assertEqual(sd._locked_part_ids(bad), set())


class PartTextTests(unittest.TestCase):
    """The candidate is what the speaker ACTUALLY said this take, verbatim
    (L1) — never assembled, never rewritten."""

    def test_it_joins_this_takes_pieces_for_that_part(self):
        # p1 spans chars 28..55 of the joined document.
        pieces = [_piece("s0", 0, 26, "First slide words go here."),
                  _piece("s1", 28, 55, "Second slide words go here.")]
        self.assertEqual(
            sd._take_text_for_part(pieces, "p1", PARTS),
            "Second slide words go here.")

    def test_a_part_this_take_did_not_cover_yields_nothing(self):
        pieces = [_piece("s0", 0, 26, "First slide words go here.")]
        self.assertEqual(sd._take_text_for_part(pieces, "p1", PARTS), "")

    def test_the_offer_hangs_on_the_parts_FIRST_snippet(self):
        """Stable across takes. 'Longest' or 'best' would move the offer to a
        different snippet between two recordings of the same paragraph."""
        pieces = [_piece("s1", 28, 40, "Second slide"),
                  _piece("s2", 41, 55, "words go here.")]
        self.assertEqual(sd._snippet_for_part(pieces, "p1", PARTS), "s1")

    def test_no_parts_no_crash(self):
        self.assertEqual(sd._take_text_for_part([], "p1", []), "")
        self.assertIsNone(sd._snippet_for_part([], "p1", []))


class CollisionTests(unittest.TestCase):
    """Content first — a snippet already carrying a suggestion keeps it."""

    class _Db:
        def __init__(self, existing=None, explode=False):
            self.existing = existing or {}
            self.explode = explode

        def get_moment_suggestions_by_arc(self, arc_id):
            if self.explode:
                raise RuntimeError("table missing")
            return self.existing

    def test_an_existing_suggestion_blocks_the_swap(self):
        db = self._Db({"s1": {"kind": "replace"}})
        self.assertTrue(sd._already_starred("s1", "a1", db))

    def test_a_clean_snippet_is_open(self):
        db = self._Db({"s9": {"kind": "replace"}})
        self.assertFalse(sd._already_starred("s1", "a1", db))

    def test_an_unreadable_ledger_FAILS_CLOSED(self):
        """The opposite direction from most reads on this path, on purpose.
        The suggestion table is snippet-keyed, so writing blind would OVERWRITE
        a correction the student was about to see. An unreadable ledger costs
        one praise offer; failing open costs a content fix, silently."""
        self.assertTrue(sd._already_starred("s1", "a1", self._Db(explode=True)))


class NoLockedPartsTests(unittest.TestCase):
    class _Db:
        def get_ideal_text_parts(self, arc_id, user_id):
            return [{"id": "p0", "text": "Nothing locked.", "locked": False}]

    def test_it_stops_before_any_expensive_work(self):
        with patch("services.acoustic_baseline.current",
                   return_value=({"f0": 1.0}, "b1")), \
             patch("services.transcript_document.build_transcript_document") as b:
            self.assertEqual(
                sd.offer_for_take("a1", "u1", "s1", database=self._Db()), 0)
            b.assert_not_called()


class GateChainTests(unittest.TestCase):
    """Stage 4's whole job: run the gates in cost order and store at most one."""

    class _Db:
        def __init__(self):
            self.upserts = []

        def get_moment_suggestions_by_arc(self, arc_id):
            return {}

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.upserts.append((snip, kind, repl, trig))
            return True

    PIECES = [_piece("s1", 28, 55, "Second slide words go here.")]

    def _run(self, *, fumble=None, verdict="fits", polish=None):
        db = self._Db()
        stored = sd._offer_best(
            [("p1", 0.9)], "a1", "sess1", PARTS, self.PIECES,
            database=db,
            gates=(lambda t: fumble,
                   lambda parts, pid, cand: "doc with swap",
                   lambda doc, cand: {"verdict": verdict, "polish": polish}),
            verdicts=("fits", "fits_with_polish"))
        return stored, db.upserts

    def test_a_clean_candidate_is_offered_verbatim(self):
        stored, upserts = self._run()
        self.assertEqual(stored, 1)
        snip, kind, repl, trig = upserts[0]
        self.assertEqual((snip, kind, trig), ("s1", "replace", "acoustic_swap"))
        self.assertEqual(repl, "Second slide words go here.")   # L1: verbatim

    def test_a_light_polish_rides_when_the_gate_returns_one(self):
        _stored, upserts = self._run(
            verdict="fits_with_polish", polish="So second slide words go here.")
        self.assertEqual(upserts[0][2], "So second slide words go here.")

    def test_a_fumbled_take_is_never_offered(self):
        stored, upserts = self._run(fumble="fillers")
        self.assertEqual((stored, upserts), (0, []))

    def test_a_broken_seam_is_never_offered(self):
        stored, upserts = self._run(verdict="no_fit")
        self.assertEqual((stored, upserts), (0, []))

    def test_at_most_one_offer_per_take(self):
        """The lane interrupts a paragraph the student already called
        finished, so a take that reopens three of them reads as the engine
        arguing with a decision rather than reporting a fact."""
        db = self._Db()
        pieces = [_piece("s1", 28, 55, "Second slide words go here."),
                  _piece("s2", 57, 83, "Third slide words go here.")]
        stored = sd._offer_best(
            [("p1", 0.9), ("p2", 0.8)], "a1", "sess1", PARTS, pieces,
            database=db,
            gates=(lambda t: None,
                   lambda parts, pid, cand: "doc",
                   lambda doc, cand: {"verdict": "fits", "polish": None}),
            verdicts=("fits", "fits_with_polish"))
        self.assertEqual(stored, sd.MAX_PER_TAKE)
        self.assertEqual(len(db.upserts), 1)
        self.assertEqual(db.upserts[0][0], "s1")   # the strongest lift first


class LiveLoopTests(unittest.TestCase):
    def test_nothing_here_can_fail_a_take(self):
        class _Boom:
            def get_ideal_text_parts(self, *a):
                raise RuntimeError("db down")
        with patch("services.acoustic_baseline.current",
                   return_value=({"f0": 1.0}, "b1")):
            self.assertEqual(
                sd.offer_for_take("a1", "u1", "s1", database=_Boom()), 0)

    def test_missing_ids_are_a_no_op(self):
        for args in ((None, "u1", "s1"), ("a1", None, "s1"), ("a1", "u1", None)):
            self.assertEqual(sd.offer_for_take(*args), 0)


if __name__ == "__main__":
    unittest.main()
