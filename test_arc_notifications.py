"""Arc lifecycle cards/notes + transcript claim-once (founder bug-batch
2026-07-06). Pure (fake db).

Run: python3 -m unittest test_arc_notifications
"""
from __future__ import annotations

import unittest
import uuid

from services.arc_notifications import (
    fire_human_check_note, maybe_fire_best_presentation_ready,
)


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


if __name__ == "__main__":
    unittest.main()


class VoiceAlbumBubbleTests(unittest.TestCase):
    """THE ALBUM ANNOUNCES ITSELF (founder 2026-08-15: "when is the bubble
    with voice album posted in the chat? if not post it once it is
    available").

    It was posted nowhere. The album filled quietly from its first day —
    capture-only on purpose, because the read surface needed signed copy — so
    the only way to find a moment in it was to already know it was there."""

    class _Db:
        def __init__(self):
            self.rows = []
            self.voice_album_introduced = False

        def list_voice_album(self, arc_id):
            return [{"snippet_id": "clip-1"}]

        def get_arc_sessions(self, arc_id):
            return [
                {"id": f"take-{index}", "analysis_state": "ready"}
                for index in range(1, 4)
            ]

        def insert_lounge_messages(self, user_id, messages):
            for m in messages:
                if any(r["client_id"] == m["client_id"] for r in self.rows):
                    continue          # mirror the real upsert idempotency
                self.rows.append({**m, "_user": user_id})
            return list(messages)

        def has_voice_album_introduction(self, user_id):
            return self.voice_album_introduced

        def mark_voice_album_introduced(self, user_id):
            self.voice_album_introduced = True
            return True

    def test_it_fires_and_points_at_the_album(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        self.assertTrue(fire_voice_album_ready(db, "u1", "arc-1"))
        self.assertEqual(len(db.rows), 1)
        body = db.rows[0]["body"].lower()
        self.assertIn("voice album", body)
        self.assertEqual(db.rows[0]["metadata"]["arc_id"], "arc-1")
        self.assertEqual(
            db.rows[0]["metadata"]["actions"], ["find_voice_album"])

    def test_idempotent_once_per_user_across_projects(self):
        # A second qualifying Project must not restart Album onboarding.
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        fire_voice_album_ready(db, "u1", "arc-1")
        self.assertFalse(fire_voice_album_ready(db, "u1", "arc-2"))
        self.assertEqual(len(db.rows), 1)

    def test_user_scoped_key_is_not_project_scoped(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        self.assertTrue(fire_voice_album_ready(db, "u1", "arc-1"))
        expected = str(uuid.uuid5(
            uuid.NAMESPACE_URL, "willab-voicealbum-user:u1"))
        self.assertEqual(db.rows[0]["client_id"], expected)

    def test_existing_user_marker_blocks_reintroduction(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        db.voice_album_introduced = True
        self.assertFalse(fire_voice_album_ready(db, "u1", "arc-2"))
        self.assertEqual(db.rows, [])

    def test_ac9_it_never_counts_or_grades(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        fire_voice_album_ready(db, "u1", "arc-1")
        body = db.rows[0]["body"].lower()
        for banned in ("score", "best", "top", "rank", "%", "points"):
            self.assertNotIn(banned, body)
        # No count either — "a moment", never "3 moments".
        self.assertFalse(any(ch.isdigit() for ch in body))

    def test_missing_user_or_arc_is_a_noop(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        self.assertFalse(fire_voice_album_ready(db, None, "arc-1"))
        self.assertFalse(fire_voice_album_ready(db, "u1", None))
        self.assertEqual(db.rows, [])

    def test_the_publish_hook_checks_eligibility_after_every_reconciliation(self):
        # The first clip can land before Take 3. A later reconciliation must
        # still be able to introduce it once the journey is complete.
        import inspect

        from routes.v2 import publish
        src = inspect.getsource(publish)
        self.assertNotIn("if _landed and", src)
        self.assertIn("fire_voice_album_ready", src)

    def test_it_waits_for_take_three(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        db.get_arc_sessions = lambda _arc: [
            {"id": "take-1", "analysis_state": "ready"},
            {"id": "take-2", "analysis_state": "ready"},
        ]
        self.assertFalse(fire_voice_album_ready(db, "u1", "arc-1"))
        self.assertEqual(db.rows, [])


class ResultsEmailDeepLinkTests(unittest.TestCase):
    """THE CTA LANDS ON THE REVIEWED TEXT (founder 2026-08-15: "does the link
    from the email lead to this particular ideal text that holds these
    reviews? if not make it a deep link").

    It led to bare /chat — for the one email whose entire subject is "your
    coach reviewed this talk", leaving the student to find the right bubble in
    a thread."""

    def test_the_journey_url_carries_the_arc(self):
        import inspect

        from services import post_session_results_email as pe
        src = inspect.getsource(pe.send_publish_results_email)
        self.assertIn("idealArc=", src)

    def test_it_falls_back_to_plain_chat_without_an_arc(self):
        # A take with no arc is a real state, and a link to nothing is worse
        # than a link to the thread that holds the card.
        import inspect

        from services import post_session_results_email as pe
        src = inspect.getsource(pe.send_publish_results_email)
        self.assertIn('else f"{_base}/chat"', src)

    def test_the_arc_is_url_escaped(self):
        import inspect

        from services import post_session_results_email as pe
        src = inspect.getsource(pe.send_publish_results_email)
        self.assertIn("_url_quote(_arc", src)

    def test_the_route_echoes_the_SAME_url_it_emailed(self):
        # results_url is returned to the caller; if the two disagreed we would
        # have two different answers to "where did we send them".
        import inspect

        from routes.v2 import publish
        src = inspect.getsource(publish)
        self.assertIn("idealArc={_q(_arc_for_link", src)
