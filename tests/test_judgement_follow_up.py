"""A judgement is always answered (founder 2026-09-29): a No on a bookmark
with no exercise sends it to the coach when the answer is saved."""
from __future__ import annotations

import unittest
from pathlib import Path

from services import confident_voice_practice as cvp
from services.judgement_follow_up import follow_up_for_judgement

ROOT = Path(__file__).resolve().parents[1]


def _snippet():
    return {"id": "snip-1", "transcript": "we think the timing matters here",
            "duration_ms": 4000, "audio_segment_path": "s/1.webm", "words": [],
            "metrics": {"wpm": 150.0, "pause_ratio": 0.1, "voiced_ratio": 0.8,
                        "audio_quality": {"reliable": True}}}


class _Db:
    def __init__(self, *, assignment=None, request=None):
        self.assignment = assignment
        self.request = request
        self.raised = []

    def get_confident_voice_exercise_assignment(self, _take, _snip):
        return self.assignment

    def get_exercise_coach_request(self, _take, _snip):
        return self.request

    def get_confident_voice_practice_candidates(self, ids):
        return [_snippet()] if "snip-1" in ids else []

    def get_snippets_by_session(self, _take):
        return [{"metrics": {"wpm": 150.0}}]

    def list_speaking_errors(self):
        return [{"error_id": "rushing", "status": "detected"}]

    def list_diagnostic_exercises(self):
        return []

    def get_active_diagnostic_exercise(self, _id):
        return None

    def request_exercise_from_coach(self, **kwargs):
        self.raised.append(kwargs)
        return {"id": "req-1", **kwargs}


def _follow(db, answer):
    return follow_up_for_judgement(
        db, take_session_id="take-1", snippet_id="snip-1",
        owner_user_id="owner-1", answer=answer)


class FollowUpTests(unittest.TestCase):
    def test_a_no_with_no_exercise_sends_the_bookmark_to_the_coach(self):
        db = _Db()
        self.assertEqual(_follow(db, "no"), "coach_request")
        self.assertEqual(len(db.raised), 1)
        raised = db.raised[0]
        self.assertEqual(raised["snippet_id"], "snip-1")
        self.assertEqual(raised["owner_user_id"], "owner-1")
        self.assertIn(raised["reason"], ("nothing_spotted", "nothing_targets_it"))
        self.assertEqual(raised["request_trace"]["lane"], "v3_judgement")

    def test_audio_unclear_raises_nothing(self):
        db = _Db()
        self.assertEqual(_follow(db, "audio_unclear"), "none")
        self.assertEqual(db.raised, [])

    def test_the_other_answers_raise_nothing_yet(self):
        # The lane opening on every bookmark is the budget change; until it
        # lands only a No sends the bookmark to the coach.
        for answer in ("yes", "in_between", "not_sure"):
            db = _Db()
            self.assertEqual(_follow(db, answer), "none", answer)
            self.assertEqual(db.raised, [])

    def test_a_moment_with_an_exercise_keeps_it(self):
        db = _Db(assignment={"selected_exercise_id": "x"})
        self.assertEqual(_follow(db, "no"), "exercise")
        self.assertEqual(db.raised, [])

    def test_a_request_already_raised_is_not_raised_twice(self):
        db = _Db(request={"id": "req-1", "resolution": None})
        self.assertEqual(_follow(db, "no"), "coach_request")
        self.assertEqual(db.raised, [])

    def test_a_failed_write_never_fails_the_answer(self):
        class _Broken(_Db):
            def request_exercise_from_coach(self, **_kwargs):
                raise RuntimeError("rpc down")
        self.assertEqual(_follow(_Broken(), "no"), "none")


class AnnotationTests(unittest.TestCase):
    """The next read serves what the request came to, on the item."""

    class _Db:
        def __init__(self, requests):
            self.requests = requests

        def get_exercise_coach_request(self, _take, snip):
            return self.requests.get(snip)

        def get_active_diagnostic_exercise(self, _id):
            return None

    def _rows(self):
        return [
            {"source": "confident_voice", "snippet_id": "a",
             "bookmark_tier": "standard"},
            {"source": "confident_voice", "snippet_id": "b",
             "bookmark_tier": "standard",
             "practice_exercise": {"exercise_id": "x"}},
            {"source": "rewrite_clarity", "snippet_id": "c"},
        ]

    def test_an_open_request_rides_the_item(self):
        db = self._Db({"a": {"id": "r", "resolution": None, "shared_at": None}})
        rows = cvp._annotate_coach_answers(
            self._rows(), take_session_id="t", owner_user_id="o",
            database=db, ground=lambda _r: None)
        self.assertEqual(rows[0]["coach_request"], {"status": "open"})
        self.assertNotIn("coach_request", rows[1])
        self.assertNotIn("coach_request", rows[2])

    def test_an_answered_unshared_request_reads_answered(self):
        db = self._Db({"a": {"id": "r", "resolution": "no_safe_match",
                             "shared_at": None}})
        rows = cvp._annotate_coach_answers(
            self._rows(), take_session_id="t", owner_user_id="o",
            database=db, ground=lambda _r: None)
        self.assertEqual(rows[0]["coach_request"], {"status": "answered"})

    def test_no_request_leaves_the_row_alone(self):
        rows = cvp._annotate_coach_answers(
            self._rows(), take_session_id="t", owner_user_id="o",
            database=self._Db({}), ground=lambda _r: None)
        self.assertNotIn("coach_request", rows[0])


class RouteTests(unittest.TestCase):
    def test_the_answer_route_reports_what_follows(self):
        source = (ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index("def v2_post_take_feedback_response")
        route = source[start:source.index("@v2_bp.route", start)]
        self.assertIn("route_owner_answer(", route)
        self.assertIn('"follow_up": follow_up', route)
        service = (ROOT / "services/judgement_follow_up.py").read_text()
        start = service.index("def route_owner_answer")
        helper = service[start:service.index("def follow_up_for_judgement")]
        # After the owner route is written, never before.
        self.assertLess(helper.index("upsert_owner_voice_album_route"),
                        helper.index("follow_up_for_judgement("))
