"""Arc lifecycle cards/notes + transcript claim-once (founder bug-batch
2026-07-06). Pure (fake db).

Run: python3 -m unittest test_arc_notifications
"""
from __future__ import annotations

import unittest

from services.arc_notifications import (
    fire_human_check_note, fire_pay_note, maybe_fire_best_presentation_ready,
)
from services.lab_recording import dedupe_window_transcripts


class _FakeDB:
    def __init__(self, sessions=None, purchase=None):
        self._sessions = sessions or []
        self._purchase = purchase
        self.inserted = []

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_arc_purchase(self, arc_id):
        return self._purchase

    def insert_lounge_messages(self, user_id, messages):
        for m in messages:
            self.inserted.append((user_id, m))
        return messages


def _sess(uid="u1", published=False, topic="My talk"):
    return {
        "user_id": uid,
        "results_published_at": "2026-07-06T00:00:00Z" if published else None,
        "intake_context": {"topic": topic},
    }


class BestPresentationCardTests(unittest.TestCase):
    # Founder #1: the best-presentation buttons appear ONLY when the coach has
    # reviewed AND the arc is paid; otherwise the transcript card.
    def test_under_three_takes_fires_nothing(self):
        db = _FakeDB(sessions=[_sess(), _sess()])
        self.assertIsNone(maybe_fire_best_presentation_ready(db, "a1"))
        self.assertEqual(db.inserted, [])

    def test_three_takes_unreviewed_fires_transcript_ready(self):
        db = _FakeDB(sessions=[_sess(), _sess(), _sess()])
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")
        _, msg = db.inserted[0]
        self.assertEqual(msg["kind"], "transcript_ready")

    def test_reviewed_but_unpaid_still_transcript_ready(self):
        db = _FakeDB(sessions=[_sess(published=True)] * 3, purchase=None)
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")

    def test_paid_but_unreviewed_still_transcript_ready(self):
        db = _FakeDB(sessions=[_sess(), _sess(), _sess()],
                     purchase={"arc_id": "a1", "user_id": "u1"})
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")

    def test_paid_but_only_partially_reviewed_still_transcript_ready(self):
        # Review must-fix: "reviewed" = EVERY take published — with the free
        # take-1 human check, any-one-published is vacuously true by take 3
        # and the bp card would fire from take-3's UPLOAD.
        db = _FakeDB(sessions=[_sess(published=True), _sess(), _sess()],
                     purchase={"arc_id": "a1", "user_id": "u1"})
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"), "transcript_ready")

    def test_reviewed_and_paid_fires_best_presentation_ready(self):
        db = _FakeDB(sessions=[_sess(published=True)] * 3,
                     purchase={"arc_id": "a1", "user_id": "u1"})
        self.assertEqual(
            maybe_fire_best_presentation_ready(db, "a1"),
            "best_presentation_ready")
        _, msg = db.inserted[0]
        self.assertEqual(msg["kind"], "best_presentation_ready")
        self.assertIn("My talk", msg["body"])

    def test_idempotent_client_id_per_arc_and_kind(self):
        db = _FakeDB(sessions=[_sess(), _sess(), _sess()])
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

    def test_pay_note_skipped_when_arc_paid(self):
        db = _FakeDB(purchase={"arc_id": "a1", "user_id": "u1"})
        self.assertFalse(fire_pay_note(db, "u1", "a1"))
        self.assertEqual(db.inserted, [])

    def test_pay_note_fires_on_unpaid_arc_with_checkout_action(self):
        db = _FakeDB(purchase=None)
        self.assertTrue(fire_pay_note(db, "u1", "a1"))
        _, msg = db.inserted[0]
        self.assertEqual(msg["metadata"]["suggested_action"], "arc_checkout")
        self.assertIn("$50", msg["body"])


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
