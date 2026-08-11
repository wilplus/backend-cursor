"""THE COACH'S WORD→SLIDE GROUND TRUTH (founder 2026-08-11).

`services/slide_boundary_metrics.py` has said it since the day it was
written: "There is no ground truth here... The only real labels available
are COACH CORRECTIONS — when a coach moves text between slides, a human has
said 'this was bucketed wrong'." That correction did not exist as data.
These tests pin the row that now carries it.

Three properties, in order of how badly getting them wrong would hurt:

  1. THE CORPUS IS APPEND-ONLY. The write inserts; it never upserts and
     never deletes. A silently overwritten label is a corpus nobody can
     compare across time — the same rule the filler-rate data lives under.
  2. THE READ IS "LATEST WINS", reverts included. A coach who withdraws a
     correction must get the pipeline's answer back, and the withdrawal is
     itself a stored label ("a human checked and the pipeline was right").
  3. THE LABEL RECORDS BOTH SIDES. Every row carries what the pipeline said
     beside what the human said, because the size of the miss is the
     measurement — a corpus of corrections alone can tell you where the
     words belong but never how far off the timeline was.

Run: python3 -m unittest test_slide_corrections
"""
from __future__ import annotations

import unittest

from tests.fakes import FakeSupabaseClient, swap_attr

import services.db as db_mod

ARC_SESSION = "11111111-1111-4111-8111-111111111111"
SNIP_A = "aaaa1111-aaaa-1111-aaaa-111111111111"
SNIP_B = "bbbb2222-bbbb-2222-bbbb-222222222222"


class RecordCorrectionTests(unittest.TestCase):
    """The write — append-only, best-effort, both sides recorded."""

    def _client(self):
        return FakeSupabaseClient({"snippet_slide_corrections": []})

    def test_a_correction_is_INSERTED_never_upserted(self):
        client = self._client()
        with swap_attr(db_mod.db, "client", client):
            ok = db_mod.db.record_snippet_slide_correction(
                session_id=ARC_SESSION, snippet_id=SNIP_A,
                slide_index=2, was_slide_index=1, corrected_by="coach-1")
        self.assertTrue(ok)
        q = client.tables["snippet_slide_corrections"]
        # The operation itself is the guarantee: an upsert would collapse the
        # trail of what the pipeline said before the human moved it.
        self.assertIn("insert", [c[0] for c in q.calls])
        self.assertNotIn("upsert", [c[0] for c in q.calls])
        self.assertNotIn("delete", [c[0] for c in q.calls])

    def test_the_row_carries_BOTH_sides_and_the_labeller(self):
        client = self._client()
        with swap_attr(db_mod.db, "client", client):
            db_mod.db.record_snippet_slide_correction(
                session_id=ARC_SESSION, snippet_id=SNIP_A,
                slide_index=2, was_slide_index=1, corrected_by="coach-1")
        row = client.tables["snippet_slide_corrections"].payload
        self.assertEqual(row["slide_index"], 2)
        self.assertEqual(row["was_slide_index"], 1)     # how far off it was
        self.assertEqual(row["corrected_by"], "coach-1")
        self.assertEqual(row["snippet_id"], SNIP_A)

    def test_a_WITHDRAWAL_is_stored_as_a_row_not_a_deletion(self):
        # "A human checked and the pipeline was right" is a label too, and a
        # rarer one than a correction — deleting it throws away the evidence.
        client = self._client()
        with swap_attr(db_mod.db, "client", client):
            db_mod.db.record_snippet_slide_correction(
                session_id=ARC_SESSION, snippet_id=SNIP_A,
                slide_index=None, was_slide_index=1)
        row = client.tables["snippet_slide_corrections"].payload
        self.assertIsNone(row["slide_index"])
        self.assertNotIn("delete", [c[0] for c in
                              client.tables["snippet_slide_corrections"].calls])

    def test_a_write_without_ids_is_refused_before_the_db(self):
        client = self._client()
        with swap_attr(db_mod.db, "client", client):
            self.assertFalse(db_mod.db.record_snippet_slide_correction(
                session_id="", snippet_id=SNIP_A, slide_index=1))
            self.assertFalse(db_mod.db.record_snippet_slide_correction(
                session_id=ARC_SESSION, snippet_id="", slide_index=1))
        self.assertEqual(client.tables, {})

    def test_a_labelling_write_never_raises_into_the_caller(self):
        # It rides along with the coach's own save; a corpus write must not be
        # able to break the review it came from.
        def boom(_q):
            raise RuntimeError("pgrst down")
        client = FakeSupabaseClient({"snippet_slide_corrections": boom})
        with swap_attr(db_mod.db, "client", client):
            self.assertFalse(db_mod.db.record_snippet_slide_correction(
                session_id=ARC_SESSION, snippet_id=SNIP_A, slide_index=1))


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
