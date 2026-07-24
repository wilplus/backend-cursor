"""Arc lifecycle cards/notes + transcript claim-once (founder bug-batch
2026-07-06). Pure (fake db).

Run: python3 -m unittest test_arc_notifications
"""
from __future__ import annotations

import unittest

from services.arc_notifications import (
    fire_human_check_note, maybe_fire_best_presentation_ready,
)
from services.lab_recording import dedupe_window_transcripts


class _FakeDB:
    def __init__(self, sessions=None, purchase=None, coach_edits=None,
                 snips_by_sid=None):
        self._sessions = sessions or []
        self._purchase = purchase
        self._coach_edits = coach_edits or {}
        self._snips = snips_by_sid or {}
        self.inserted = []

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_arc_purchase(self, arc_id):
        return self._purchase

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))

    def get_training_labels(self, sid):
        return []

    def get_coach_best_presentation_edits(self, arc_id):
        return dict(self._coach_edits)

    def get_best_presentation_edits(self, arc_id):
        return {}

    def insert_lounge_messages(self, user_id, messages):
        for m in messages:
            self.inserted.append((user_id, m))
        return messages


def _sess(sid="s1", uid="u1", published=False, topic="My talk"):
    # ONE slide, ONE snippet — build_best_presentation composes exactly one
    # slide so coach_finalized only needs {0: <text>} to control it.
    return {
        "id": sid,
        "user_id": uid,
        "results_published_at": "2026-07-06T00:00:00Z" if published else None,
        "intake_context": {
            "topic": topic,
            "slides": [{"title": "Slide 1", "body": "p"}],
            "slide_advances": [{"index": 0, "t_ms": 0}],
        },
    }


def _snip(sid):
    return {"id": sid, "start_offset_ms": 0, "duration_ms": 1000,
            "transcript": "a line", "storage_path": f"s3://{sid}",
            "metrics": {"overall_score": 0.5}}


class BestPresentationCardTests(unittest.TestCase):
    # Founder #1: the best-presentation buttons appear ONLY when the coach has
    # FINALIZED the ideal text (corrected every slide — the real signal from
    # services.best_presentation) AND the arc is paid; otherwise the
    # transcript card.
    def _sessions(self, n, **kw):
        return [_sess(sid=f"s{i}", **kw) for i in range(n)]

    def _snips(self, n):
        return {f"s{i}": [_snip(f"c{i}")] for i in range(n)}

    def test_under_three_takes_fires_nothing(self):
        db = _FakeDB(sessions=self._sessions(2), snips_by_sid=self._snips(2))
        self.assertIsNone(maybe_fire_best_presentation_ready(db, "a1"))
        self.assertEqual(db.inserted, [])

    def test_three_takes_unfinalized_fires_transcript_ready(self):
        db = _FakeDB(sessions=self._sessions(3), snips_by_sid=self._snips(3))
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")
        _, msg = db.inserted[0]
        self.assertEqual(msg["kind"], "transcript_ready")

    def test_finalized_but_unpaid_still_transcript_ready(self):
        db = _FakeDB(sessions=self._sessions(3), snips_by_sid=self._snips(3),
                     purchase=None, coach_edits={0: "coach's corrected line"})
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")

    def test_paid_but_unfinalized_still_transcript_ready(self):
        db = _FakeDB(sessions=self._sessions(3), snips_by_sid=self._snips(3),
                     purchase={"arc_id": "a1", "user_id": "u1"})
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")

    def test_paid_and_all_takes_published_but_not_finalized_still_transcript(self):
        # Review must-fix (retained): "all takes published" is NOT the same as
        # coach_finalized — with the free take-1 human check + auto-publish,
        # a proxy on published-status alone would fire the bp card too early.
        db = _FakeDB(
            sessions=self._sessions(3, published=True),
            snips_by_sid=self._snips(3),
            purchase={"arc_id": "a1", "user_id": "u1"},
        )
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")

    def test_finalized_and_paid_fires_best_presentation_ready(self):
        db = _FakeDB(sessions=self._sessions(3), snips_by_sid=self._snips(3),
                     purchase={"arc_id": "a1", "user_id": "u1"},
                     coach_edits={0: "coach's corrected line"})
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"),
            "best_presentation_ready")
        _, msg = db.inserted[0]
        self.assertEqual(msg["kind"], "best_presentation_ready")
        self.assertIn("My talk", msg["body"])

    def test_idempotent_client_id_per_arc_and_kind(self):
        db = _FakeDB(sessions=self._sessions(3), snips_by_sid=self._snips(3))
        maybe_fire_best_presentation_ready(db, "a1")
        maybe_fire_best_presentation_ready(db, "a1")
        ids = [m["client_id"] for _, m in db.inserted]
        self.assertEqual(len(set(ids)), 1)  # same uuid5 → server dedupes


class NotesTests(unittest.TestCase):
    def test_human_check_note_inserts(self):
        db = _FakeDB()
        self.assertTrue(fire_human_check_note(db, "u1", "a1"))
        _, msg = db.inserted[0]
        self.assertEqual(msg["kind"], "text")
        self.assertEqual(msg["metadata"]["note"], "human_check")


class DedupeWindowTranscriptsTests(unittest.TestCase):
    # Founder #2: a sentence straddling two windows must appear ONCE, in the
    # window where it was mostly spoken.
    def test_straddling_segment_goes_to_larger_overlap(self):
        windows = [(0, 5000), (5000, 10000)]
        segments = [
            {"start": 0.0, "end": 4.0, "text": "Sentence A."},
            # straddles the boundary, mostly in window 2 (4.5s→8s)
            {"start": 4.5, "end": 8.0, "text": "Sentence B."},
        ]
        out = dedupe_window_transcripts(windows, segments)
        self.assertEqual(out[0], "Sentence A.")
        self.assertEqual(out[1], "Sentence B.")  # once, not in both

    def test_each_sentence_appears_exactly_once(self):
        windows = [(0, 3000), (2800, 6000), (5800, 9000)]  # padded overlaps
        segments = [
            {"start": 0.0, "end": 2.9, "text": "One."},
            {"start": 2.9, "end": 5.9, "text": "Two."},
            {"start": 5.9, "end": 8.9, "text": "Three."},
        ]
        joined = " ".join(dedupe_window_transcripts(windows, segments))
        for word in ("One.", "Two.", "Three."):
            self.assertEqual(joined.count(word), 1, word)

    def test_empty_inputs(self):
        self.assertEqual(dedupe_window_transcripts([], []), [])
        self.assertEqual(dedupe_window_transcripts([(0, 1000)], []), [""])


if __name__ == "__main__":
    unittest.main()
