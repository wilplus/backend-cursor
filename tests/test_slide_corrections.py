"""THE COACH'S WORD→SLIDE GROUND TRUTH (founder 2026-08-11).

`services/slide_boundary_metrics.py` has said it since the day it was
written: "There is no ground truth here... The only real labels available
are COACH CORRECTIONS — when a coach moves text between slides, a human has
said 'this was bucketed wrong'." That correction did not exist as data.
These tests pin the rows that carry it.

The slide-mapping correction control and its writer were retired with the
arc-level delivery (founder 2026-09-30, B5; contract 65): no new row is
written. The corpus already recorded stays, and the READ stays load-bearing,
"latest wins", reverts included: a withdrawal is itself a stored label ("a
human checked and the pipeline was right"), and the Ideal Text's slide
bucketing (services/transcript_document.py) still reads it.

Run: python3 -m unittest tests.test_slide_corrections
"""
from __future__ import annotations

import unittest

from tests.fakes import FakeSupabaseClient, swap_attr

import services.db as db_mod

ARC_SESSION = "11111111-1111-4111-8111-111111111111"
SNIP_A = "aaaa1111-aaaa-1111-aaaa-111111111111"
SNIP_B = "bbbb2222-bbbb-2222-bbbb-222222222222"


class ReadCorrectionsTests(unittest.TestCase):
    """The read — latest wins, reverts land as None, missing table degrades."""

    def test_latest_row_per_snippet_wins(self):
        # Newest-first from the query; first seen per snippet is the current
        # answer. Two corrections on one snippet = the later one.
        client = FakeSupabaseClient({"snippet_slide_corrections": [
            {"snippet_id": SNIP_A, "slide_index": 3},   # newest
            {"snippet_id": SNIP_B, "slide_index": 0},
            {"snippet_id": SNIP_A, "slide_index": 2},   # older, superseded
        ]})
        with swap_attr(db_mod.db, "client", client):
            out = db_mod.db.get_snippet_slide_corrections(ARC_SESSION)
        self.assertEqual(out, {SNIP_A: 3, SNIP_B: 0})

    def test_a_withdrawal_reads_as_None_not_as_absent(self):
        # The distinction the pipeline needs: absent = never corrected (use
        # the timeline); None = corrected then withdrawn (use the timeline).
        # Both defer to the timeline, but only one is a human decision, and
        # the corpus must be able to tell them apart.
        client = FakeSupabaseClient({"snippet_slide_corrections": [
            {"snippet_id": SNIP_A, "slide_index": None},
            {"snippet_id": SNIP_A, "slide_index": 2},
        ]})
        with swap_attr(db_mod.db, "client", client):
            out = db_mod.db.get_snippet_slide_corrections(ARC_SESSION)
        self.assertIn(SNIP_A, out)
        self.assertIsNone(out[SNIP_A])

    def test_the_read_is_ordered_newest_first(self):
        # "Latest wins" is only true if the query says so — assert the order
        # clauses rather than trusting the row order a fake happened to give.
        client = FakeSupabaseClient({"snippet_slide_corrections": []})
        with swap_attr(db_mod.db, "client", client):
            db_mod.db.get_snippet_slide_corrections(ARC_SESSION)
        orders = [c for c in
                  client.tables["snippet_slide_corrections"].calls
                  if c[0] == "order"]
        self.assertTrue(orders)
        self.assertEqual(orders[0][1][0], "created_at")
        self.assertTrue(all(o[2].get("desc") is True for o in orders))

    def test_a_missing_table_degrades_to_the_pipeline_not_to_silence(self):
        def missing(_q):
            raise RuntimeError(
                'relation "snippet_slide_corrections" does not exist')
        client = FakeSupabaseClient({"snippet_slide_corrections": missing})
        with swap_attr(db_mod.db, "client", client):
            self.assertEqual(
                db_mod.db.get_snippet_slide_corrections(ARC_SESSION), {})
            self.assertEqual(
                db_mod.db.list_snippet_slide_corrections(ARC_SESSION), [])

    def test_no_session_reads_nothing(self):
        client = FakeSupabaseClient({"snippet_slide_corrections": []})
        with swap_attr(db_mod.db, "client", client):
            self.assertEqual(db_mod.db.get_snippet_slide_corrections(""), {})
        self.assertEqual(client.tables, {})


class CorpusShapeTests(unittest.TestCase):
    """The trail — every row, newest first, is the training corpus."""

    def test_the_audit_trail_returns_every_row_including_superseded_ones(self):
        rows = [
            {"snippet_id": SNIP_A, "slide_index": 3, "was_slide_index": 1},
            {"snippet_id": SNIP_A, "slide_index": 2, "was_slide_index": 1},
        ]
        client = FakeSupabaseClient({"snippet_slide_corrections": rows})
        with swap_attr(db_mod.db, "client", client):
            out = db_mod.db.list_snippet_slide_corrections(ARC_SESSION)
        # Both rows: the corpus wants the history, the pipeline wants the head.
        self.assertEqual(len(out), 2)
        self.assertEqual([r["slide_index"] for r in out], [3, 2])


if __name__ == "__main__":
    unittest.main()
