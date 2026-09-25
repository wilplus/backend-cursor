"""The history of learning (founder 2026-09-25).

"just make it a history of learning; there was a video then the practice and
they can scroll and actually see how it changed."

These hold the two fences that decide what a speaker may be shown, and the
one property that makes the whole idea work: it reads, and never writes.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock

for _module in ("supabase", "sentry_sdk"):
    if _module not in sys.modules:
        sys.modules[_module] = types.ModuleType(_module)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None
    sys.modules["supabase"].Client = object
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None

from services import learning_history as history


SID1 = "11111111-1111-4111-8111-111111111111"
SID2 = "22222222-2222-4222-8222-222222222222"


def _database(*, versions, sessions, practice=None, attempts=()):
    db = Mock()
    db.list_ideal_text_versions.return_value = list(versions)
    db.takes.get_arc_sessions.return_value = list(sessions)
    db.get_confident_voice_practice_by_take.return_value = practice
    db.list_confident_voice_practice_attempts.return_value = list(attempts)
    return db


SHARED = {
    "id": "p1",
    "coach_shared_at": "2026-09-01T10:00:00Z",
    "coach_shared_exercise": {
        "title": "Land the last word",
        "instruction": "Say the final word at full volume.",
        "explanation_video_url": "https://example.com/v.mp4",
    },
    "professional_coach_decision": "no",
    "selected_attempt_coach_decision": "no",
}


class TheChainTests(unittest.TestCase):
    def test_every_version_is_a_chapter_oldest_first(self):
        db = _database(
            versions=[
                {"version": 1, "text": "First words.", "created_at": "a"},
                {"version": 2, "text": "Second words.", "created_at": "b"},
            ],
            sessions=[],
        )
        out = history.build_learning_history(db, "arc-1")
        self.assertEqual([e["version"] for e in out["entries"]], [1, 2])
        self.assertEqual(out["entries"][0]["text"], "First words.")
        self.assertEqual(out["history_starts_at"], "a")

    def test_the_words_the_coach_spoke_about_survive_a_rewrite(self):
        """The whole point. The note used to be looked up by matching its
        phrase against the CURRENT document, so a rewrite dropped it. Here
        the old words are their own entry and the rewrite is the next one."""
        db = _database(
            versions=[
                {"version": 1, "text": "and that's basically it, thanks",
                 "created_at": "a"},
                {"version": 2, "text": "That's the idea. Thank you.",
                 "created_at": "b"},
            ],
            sessions=[{"id": SID1, "take_index": 1}],
            practice=SHARED,
        )
        out = history.build_learning_history(db, "arc-1")
        first, second = out["entries"]
        self.assertIn("basically it", first["text"])
        self.assertIsNotNone(first["coach"])
        self.assertEqual(first["coach"]["video_ref"],
                         "https://example.com/v.mp4")
        # The rewrite does not erase the chapter it replaced.
        self.assertIn("That's the idea", second["text"])

    def test_a_chapter_with_no_coach_and_no_practice_is_still_a_chapter(self):
        db = _database(
            versions=[{"version": 1, "text": "Words.", "created_at": "a"}],
            sessions=[{"id": SID1, "take_index": 1}],
            practice=None,
        )
        out = history.build_learning_history(db, "arc-1")
        self.assertEqual(len(out["entries"]), 1)
        self.assertIsNone(out["entries"][0]["coach"])
        self.assertEqual(out["entries"][0]["practice"], [])

    def test_a_snapshot_with_no_words_is_not_a_blank_chapter(self):
        db = _database(
            versions=[
                {"version": 1, "text": "   ", "created_at": "a"},
                {"version": 2, "text": "Real words.", "created_at": "b"},
            ],
            sessions=[],
        )
        out = history.build_learning_history(db, "arc-1")
        self.assertEqual([e["version"] for e in out["entries"]], [2])

    def test_a_project_older_than_the_table_gets_a_short_chain_not_a_wrong_one(self):
        db = _database(versions=[], sessions=[{"id": SID1, "take_index": 1}])
        out = history.build_learning_history(db, "arc-1")
        self.assertEqual(out["entries"], [])
        self.assertIsNone(out["history_starts_at"])


class TheBlindCoachFenceTests(unittest.TestCase):
    """A coach's judgement is made blind and never reaches the speaker. Only
    what they deliberately SHARED may appear in a history of learning."""

    def test_work_the_coach_never_shared_does_not_appear(self):
        unshared = dict(SHARED)
        unshared.pop("coach_shared_at")
        db = _database(
            versions=[{"version": 1, "text": "Words.", "created_at": "a"}],
            sessions=[{"id": SID1, "take_index": 1}],
            practice=unshared,
        )
        out = history.build_learning_history(db, "arc-1")
        self.assertIsNone(out["entries"][0]["coach"])

    def test_no_coach_verdict_reaches_the_payload_in_any_form(self):
        db = _database(
            versions=[{"version": 1, "text": "Words.", "created_at": "a"}],
            sessions=[{"id": SID1, "take_index": 1}],
            practice=SHARED,
        )
        out = history.build_learning_history(db, "arc-1")
        rendered = repr(out)
        for banned in history.BLIND_COACH_FIELDS:
            self.assertNotIn(banned, rendered)
        # The word itself, not just the key: the practice row above says "no".
        self.assertNotIn("professional_coach_decision", rendered)


class TheAC9FenceTests(unittest.TestCase):
    def test_practice_is_events_never_a_tally(self):
        """A number beside a person's attempts invites reading as a score,
        and there is nothing here to score."""
        db = _database(
            versions=[{"version": 1, "text": "Words.", "created_at": "a"}],
            sessions=[{"id": SID1, "take_index": 1}],
            practice=SHARED,
            attempts=[
                {"attempt_index": 1, "created_at": "t1"},
                {"attempt_index": 2, "created_at": "t2"},
            ],
        )
        out = history.build_learning_history(db, "arc-1")
        entry = out["entries"][0]
        self.assertEqual(
            entry["practice"],
            [{"attempt_index": 1, "recorded_at": "t1"},
             {"attempt_index": 2, "recorded_at": "t2"}],
        )
        self.assertNotIn("count", repr(entry))
        self.assertNotIn("score", repr(entry))


class ItOnlyEverReadsTests(unittest.TestCase):
    def test_nothing_is_written_while_assembling_a_history(self):
        db = _database(
            versions=[{"version": 1, "text": "Words.", "created_at": "a"}],
            sessions=[{"id": SID1, "take_index": 1}],
            practice=SHARED,
            attempts=[{"attempt_index": 1, "created_at": "t1"}],
        )
        history.build_learning_history(db, "arc-1")
        for called in (c[0] for c in db.mock_calls):
            self.assertFalse(
                any(verb in called for verb in
                    ("insert", "update", "upsert", "delete", "set_")),
                f"the history must not write: {called}",
            )

    def test_a_database_that_refuses_degrades_to_a_shorter_history(self):
        db = Mock()
        db.list_ideal_text_versions.side_effect = RuntimeError("down")
        out = history.build_learning_history(db, "arc-1")
        self.assertEqual(out["entries"], [])

    def test_a_practice_read_that_fails_does_not_lose_the_words(self):
        db = _database(
            versions=[{"version": 1, "text": "Words.", "created_at": "a"}],
            sessions=[{"id": SID1, "take_index": 1}],
        )
        db.get_confident_voice_practice_by_take.side_effect = RuntimeError("x")
        out = history.build_learning_history(db, "arc-1")
        self.assertEqual(out["entries"][0]["text"], "Words.")
        self.assertIsNone(out["entries"][0]["coach"])


if __name__ == "__main__":
    unittest.main()
