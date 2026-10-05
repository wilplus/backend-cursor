"""A word for this Take (founder 2026-09-30, B3; build plan P2-5).

Pins:
  * one word per (Take, coach): a save replaces it; share stamps it once;
  * a word needs words or a video;
  * the speaker's coach message is the shared word of the Take on screen
    (N48.3 Q11 A), never another Take's, and falls back to that Take's
    arc-level publish only where it has no word;
  * sharing brings the project's Ideal Text bubble back, best-effort;
  * the route needs a coach and a real session.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest import mock

from services import coach_message_read as cmr
from services import coach_take_word as ctw

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self):
        self.words: dict[tuple[str, str], dict] = {}
        self.bumped = []

    def upsert_coach_take_word(self, *, take_session_id, coach_id, text, video_ref, share):
        key = (take_session_id, coach_id)
        row = dict(self.words.get(key) or {})
        row.update({"take_session_id": take_session_id, "coach_id": coach_id,
                    "text": text, "video_ref": video_ref, "updated_at": "t2"})
        if share and not row.get("shared_at"):
            row["shared_at"] = "t1"
        self.words[key] = row
        return row

    def get_coach_take_word(self, take, coach):
        return self.words.get((take, coach))

    def list_shared_coach_take_words(self, ids):
        return [w for (t, _c), w in self.words.items() if t in ids and w.get("shared_at")]

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": "owner-1", "arc_id": "arc-1"}


class SaveTests(unittest.TestCase):
    def test_a_word_is_saved_replaced_and_shared_once(self):
        db = _Db()
        first = ctw.save_take_word(db, take_session_id="take-1", coach_id="coach-1",
                                   body={"text": "  Good  Take. "})
        self.assertEqual(first["text"], "Good Take.")
        self.assertIsNone(first["shared_at"])
        with mock.patch("services.arc_notifications.bump_ideal_bubble") as bump:
            shared = ctw.save_take_word(db, take_session_id="take-1", coach_id="coach-1",
                                        body={"text": "Good Take.", "share": True})
            self.assertEqual(shared["shared_at"], "t1")
            bump.assert_called_once_with(db, "owner-1", "arc-1")
        again = ctw.save_take_word(db, take_session_id="take-1", coach_id="coach-1",
                                   body={"text": "Better words.", "share": True})
        self.assertEqual(again["text"], "Better words.")
        self.assertEqual(again["shared_at"], "t1")
        self.assertEqual(len(db.words), 1)

    def test_a_word_needs_words_or_a_video(self):
        with self.assertRaises(ctw.TakeWordRefusal):
            ctw.save_take_word(_Db(), take_session_id="t", coach_id="c", body={"text": "  "})
        row = ctw.save_take_word(_Db(), take_session_id="t", coach_id="c",
                                 body={"video_ref": "https://v/x.mp4"})
        self.assertEqual(row["video_url"], "https://v/x.mp4")

    def test_the_read_is_this_coach_s_own(self):
        db = _Db()
        ctw.save_take_word(db, take_session_id="t", coach_id="c1", body={"text": "mine"})
        self.assertEqual(ctw.take_word_for(db, take_session_id="t", coach_id="c1")["text"], "mine")
        self.assertIsNone(ctw.take_word_for(db, take_session_id="t", coach_id="c2"))


class SpeakerTests(unittest.TestCase):
    def _three_takes(self):
        db = _Db()
        db.words[("take-1", "c")] = {"take_session_id": "take-1", "coach_id": "c",
                                     "text": "Take one word", "shared_at": "2026-09-30T10:00"}
        db.words[("take-2", "c")] = {"take_session_id": "take-2", "coach_id": "c",
                                     "text": "Take two word", "shared_at": "2026-09-30T11:00"}
        db.words[("take-3", "c")] = {"take_session_id": "take-3", "coach_id": "c",
                                     "text": "unshared", "shared_at": None}
        sessions = [{"id": "take-1", "take_index": 1}, {"id": "take-2", "take_index": 2},
                    {"id": "take-3", "take_index": 3}]
        return db, sessions

    def test_the_speaker_reads_the_shared_word_of_the_take_on_screen(self):
        db, sessions = self._three_takes()
        out = cmr.coach_message_for(db, sessions, "take-2")
        self.assertEqual(out["text"], "Take two word")
        self.assertEqual(out["take_index"], 2)
        self.assertEqual(out["published_at"], "2026-09-30T11:00")
        self.assertEqual(out["take_session_id"], "take-2")

    def test_a_word_belongs_to_its_take(self):
        """N48.3 Q11 A: Take 1 on screen reads Take 1's word, not the later
        Take 2 word; Take 3 on screen, whose word is unshared, reads none."""
        db, sessions = self._three_takes()
        self.assertEqual(cmr.coach_message_for(db, sessions, "take-1")["text"],
                         "Take one word")
        self.assertIsNone(cmr.coach_message_for(db, sessions, "take-3"))

    def test_the_latest_of_two_coaches_on_one_take(self):
        db, sessions = self._three_takes()
        db.words[("take-2", "c2")] = {"take_session_id": "take-2", "coach_id": "c2",
                                      "text": "Second coach", "shared_at": "2026-09-30T12:00"}
        self.assertEqual(cmr.coach_message_for(db, sessions, "take-2")["text"],
                         "Second coach")

    def test_without_a_word_the_publish_still_serves(self):
        class _Pub(_Db):
            def get_coach_review_revision(self, _id):
                return {"overall_message": "Published words", "published_at": "p"}
        db = _Pub()
        sessions = [{"id": "take-1", "take_index": 1, "results_published_at": "x",
                     "coach_review_revision_id": "rev"}]
        self.assertEqual(cmr.coach_message_for(db, sessions, "take-1")["text"],
                         "Published words")

    def test_a_failed_word_read_never_costs_the_message(self):
        class _Down(_Db):
            def list_shared_coach_take_words(self, ids):
                raise RuntimeError("down")
        self.assertIsNone(ctw.latest_shared_word(_Down(), [{"id": "t"}]))


class RouteTests(unittest.TestCase):
    def test_the_routes_are_coach_only_and_the_video_is_behind_the_gate(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        for name in ("v2_coach_take_word", "v2_coach_exercise_request_video"):
            start = source.index(f"def {name}")
            head = source[source.rindex("@v2_bp.route", 0, start):start]
            self.assertIn("@require_admin_or_coach", head, name)
        start = source.index("def v2_coach_exercise_request_video")
        body = source[start:source.index("@v2_bp.route", start)]
        self.assertLess(body.index("_moment_gate(session_id, snippet_id)"),
                        body.index("store_answer_video("))

    def test_the_migration_holds_the_standing_rules(self):
        sql = (ROOT / "migrations/a_word_for_this_take.sql").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS public.coach_take_words", sql)
        self.assertIn("ALTER TABLE public.coach_take_words ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("'note_written'", sql)
        self.assertIn("answer_video_ref", sql)


if __name__ == "__main__":
    unittest.main()
