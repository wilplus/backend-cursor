"""The acoustic swap lane, stage 4 — the orchestration (founder 2026-08-13).

Run: python3 -m unittest test_swap_detector
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import swap_detector as sd


# ⚠️ THE REAL DB PROJECTION, NOT A CONVENIENT ONE. `get_ideal_text_parts`
# selects `id, ord, text` and adds `locked_at` only under with_lock=True
# (services/db.py). There is no `locked` column anywhere — `locked` is minted
# by ideal_text_parts.serve() for the WIRE, folding the timestamp to a boolean.
#
# The first version of this file invented {"locked": True} rows, so it agreed
# with the code instead of with the database, and the lane shipped unable to
# fire with a green suite behind it. Every fixture here now mirrors a real
# row shape; if that shape changes, these tests must fail.
PARTS = [
    {"id": "p0", "ord": 0, "text": "First slide words go here.",
     "locked_at": None},
    {"id": "p1", "ord": 1, "text": "Second slide words go here.",
     "locked_at": "2026-08-13T10:00:00Z"},
    {"id": "p2", "ord": 2, "text": "Third slide words go here.",
     "locked_at": "2026-08-13T10:01:00Z"},
]

# What the projection returns when the caller FORGETS with_lock=True — the
# exact bug, pinned so it cannot come back unnoticed.
PARTS_NO_LOCK_FIELD = [{k: v for k, v in p.items() if k != "locked_at"}
                       for p in PARTS]


def _piece(snippet_id, start, end, text, slide_index=None):
    """A document piece. `slide_index` is stamped by
    build_transcript_document on every piece and is the ONLY key that maps
    across takes — start/end are per-document character offsets."""
    p = {"snippet_id": snippet_id, "start": start, "end": end, "text": text}
    if slide_index is not None:
        p["slide_index"] = slide_index
    return p


class LockedPartTests(unittest.TestCase):
    def test_only_locked_parts_are_eligible(self):
        self.assertEqual(sd._locked_part_ids(PARTS), {"p1", "p2"})

    def test_the_lock_is_read_from_locked_at_not_locked(self):
        """THE SHIPPED BUG, pinned. `locked` is a wire field minted by
        serve(); a stored row only ever carries `locked_at`. Reading the
        wrong one made every part read as open, so the lane declined on
        100% of takes through a branch whose log says 'no locked parts'."""
        wire_shaped = [{"id": "p1", "ord": 1, "text": "x", "locked": True}]
        self.assertEqual(sd._locked_part_ids(wire_shaped), set())

    def test_a_projection_without_the_lock_column_yields_nothing(self):
        """The other half: even correct key-reading finds nothing if the
        caller omitted with_lock=True. offer_for_take must pass it."""
        self.assertEqual(sd._locked_part_ids(PARTS_NO_LOCK_FIELD), set())

    def test_offer_for_take_ASKS_for_the_lock_column(self):
        import inspect
        src = inspect.getsource(sd.offer_for_take)
        self.assertIn("with_lock=True", src)

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


class CoordinateSystemTests(unittest.TestCase):
    """The bug UNDER the two shape bugs, and the one that would have survived
    fixing them: the take and the document are measured in different strings.

    `part_spans(parts)` lays character offsets over `joined(parts)` — the
    DOCUMENT. But this take's pieces come from build_transcript_document with a
    session_id, whose start/end index THAT TAKE's own assembled text. Feeding
    the take's offsets to the document's spans buckets pieces onto whichever
    paragraph sits at the same character index — plausible numbers, wrong
    pieces. `slide_index` is the key that genuinely maps across takes, which is
    why the take side is bucketed by slide and joined back through the
    document's own pieces."""

    # The take said its second slide in far fewer characters than the document
    # devotes to it — so document offsets and take offsets disagree, which is
    # the normal case rather than a contrived one.
    TAKE_PIECES = [
        {**_piece("t0", 0, 9, "Slide one", slide_index=0),
         "metrics": {"f0_mean": 120.0}},
        {**_piece("t1", 11, 21, "Slide two!", slide_index=1),
         "metrics": {"f0_mean": 190.0}},
    ]
    DOC_PIECES = [
        {**_piece("d0", 0, 26, "First slide words go here.", slide_index=0),
         "metrics": {"f0_mean": 118.0}},
        {**_piece("d1", 28, 55, "Second slide words go here.", slide_index=1),
         "metrics": {"f0_mean": 140.0}},
    ]

    def test_the_take_is_bucketed_by_SLIDE_not_by_character_offset(self):
        by_slide = sd._take_z_by_slide(self.TAKE_PIECES)
        self.assertEqual(set(by_slide), {0, 1})

    def test_a_piece_with_no_slide_index_is_dropped_not_guessed(self):
        pieces = [{**_piece("x", 0, 5, "words"), "metrics": {"f0_mean": 1.0}}]
        self.assertEqual(sd._take_z_by_slide(pieces), {})

    def test_the_document_supplies_the_part_to_slide_join(self):
        # p0 spans 0..26 and p1 spans 28..55 of the joined parts document,
        # which is where the DOC pieces are anchored — so part_at is valid
        # for them, and only for them.
        self.assertEqual(sd._part_slides(self.DOC_PIECES, PARTS),
                         {"p0": 0, "p1": 1})

    def test_take_offsets_would_have_mapped_to_the_WRONG_part(self):
        """The proof the old code was wrong rather than merely fragile: run
        the take's pieces through the DOCUMENT's spans, as the shipped version
        did, and piece t1 — slide two — lands on part p0."""
        from services.ideal_text_parts import part_at, part_spans
        spans = part_spans(PARTS)
        landed = part_at(spans, 11, 21)          # the take's slide-two offsets
        self.assertEqual(landed["id"], "p0")     # …lands on slide ONE's part
        # Via slide index it maps where it belongs.
        self.assertEqual(sd._part_slides(self.DOC_PIECES, PARTS)["p1"], 1)

    def test_junk_never_raises(self):
        for bad in (None, [], [None, 42], {"a": 1}):
            self.assertEqual(sd._take_z_by_slide(bad), {})
            self.assertEqual(sd._part_slides(bad, PARTS), {})
            self.assertEqual(sd._part_slides(self.DOC_PIECES, bad), {})
