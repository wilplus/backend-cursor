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

    def test_the_other_answers_raise_only_when_a_problem_was_recognised(self):
        # Yes, In-between and Not sure send the bookmark to the coach when a
        # problem fired on the clip and nothing targets it; with nothing
        # recognised they raise nothing (founder 2026-09-29).
        original = cvp.observed_problem_tags
        try:
            cvp.observed_problem_tags = lambda *_a, **_k: set()
            for answer in ("yes", "in_between", "not_sure"):
                db = _Db()
                self.assertEqual(_follow(db, answer), "none", answer)
                self.assertEqual(db.raised, [])
            cvp.observed_problem_tags = lambda *_a, **_k: {"rushing"}
            for answer in ("yes", "in_between", "not_sure"):
                db = _Db()
                self.assertEqual(_follow(db, answer), "coach_request", answer)
                self.assertEqual(db.raised[0]["reason"], "nothing_targets_it")
        finally:
            cvp.observed_problem_tags = original

    def test_a_no_raises_even_with_nothing_recognised(self):
        original = cvp.observed_problem_tags
        try:
            cvp.observed_problem_tags = lambda *_a, **_k: set()
            db = _Db()
            self.assertEqual(_follow(db, "no"), "coach_request")
            self.assertEqual(db.raised[0]["reason"], "nothing_spotted")
        finally:
            cvp.observed_problem_tags = original

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


class EveryBookmarkTests(unittest.TestCase):
    """The lane on every bookmark (founder 2026-09-29): each Confident Voice
    item gets the exercise matched to its own clip; nothing is written."""

    class _Db:
        def __init__(self, fired_by_snippet):
            self.fired = fired_by_snippet
            self.assigned = []
            self.raised = []

        def list_diagnostic_exercises(self):
            return [{"exercise_id": "land"}]

        def get_active_diagnostic_exercise(self, exercise_id):
            return {"exercise_id": "land", "version": 1, "title": "Land it",
                    "instruction": "", "introduction_copy": "",
                    "explanation_video_url": "https://cdn.example/x.mp4",
                    "acoustic_problem_tags": ["rushing"],
                    "matching_criteria": {},
                    "supported_confidence_patterns": [
                        "low_confidence_rushing_dominant", "near_confident",
                        "confident"]} if exercise_id == "land" else None

        def list_speaking_errors(self):
            return [{"error_id": "rushing", "status": "detected"}]

        def get_confident_voice_practice_candidates(self, ids):
            return [dict(_snippet(), id=i) for i in ids if i in self.fired]

        def get_snippets_by_session(self, _take):
            return [{"metrics": {"wpm": 150.0}}]

        def get_confident_voice_practice_by_moment(self, _take, _snip, owner=None):
            return None

        def get_exercise_coach_request(self, _take, _snip):
            return None

        def assign_confident_voice_exercise(self, **kwargs):
            self.assigned.append(kwargs["snippet_id"])
            return {"selected_exercise_id": kwargs["candidates"][0]["exercise_id"]}

        def completed_exercise_before(self, *_args):
            return False

        def request_exercise_from_coach(self, **kwargs):
            self.raised.append(kwargs)
            return kwargs

    def _attach(self, db, rows, withhold=False):
        original = cvp.exercise_eligibility
        cvp.exercise_eligibility = lambda snippet, **_k: {
            "eligible": True, "pattern": "near_confident", "priority": 3,
            "signals": db.fired[snippet["id"]], "snapshot": {}}
        try:
            return cvp.attach_v3_exercise_offer(
                rows, take_session_id="take-1", owner_user_id="owner-1",
                database=db, ground=lambda _row: {"slide_index": 0},
                verbal_problem=withhold)
        finally:
            cvp.exercise_eligibility = original

    def _rows(self):
        return [
            {"source": "confident_voice", "snippet_id": "a",
             "bookmark_tier": "exercise"},
            {"source": "confident_voice", "snippet_id": "b",
             "bookmark_tier": "standard"},
            {"source": "confident_voice", "snippet_id": "c",
             "bookmark_tier": "most_confident"},
        ]

    def test_every_matched_bookmark_carries_its_own_exercise(self):
        db = self._Db({"a": {"insufficient_pauses": True},
                       "b": {"insufficient_pauses": True},
                       "c": {}})
        rows = self._attach(db, self._rows())
        self.assertEqual(rows[0]["practice_exercise"]["exercise_id"], "land")
        self.assertEqual(rows[1]["practice_exercise"]["exercise_id"], "land")
        self.assertNotIn("practice_exercise", rows[2])
        self.assertEqual(sorted(db.assigned), ["a", "b"])
        # Nothing recognised on c: a judgement other than No raises nothing.
        self.assertIs(rows[2]["problem_recognised"], False)
        # And nothing is written at read time: requests come on the judgement.
        self.assertEqual(db.raised, [])

    def test_a_recognised_problem_nothing_targets_is_said_on_the_item(self):
        class _NoLibrary(self._Db):
            def list_diagnostic_exercises(self):
                return []
        db = _NoLibrary({"a": {"insufficient_pauses": True}, "b": {}, "c": {}})
        rows = self._attach(db, self._rows())
        self.assertIs(rows[0]["problem_recognised"], True)
        self.assertIs(rows[1]["problem_recognised"], False)
        self.assertNotIn("practice_exercise", rows[0])

    def test_a_rewrite_on_the_paragraph_withholds_that_bookmark_only(self):
        db = self._Db({"a": {"insufficient_pauses": True},
                       "b": {"insufficient_pauses": True}, "c": {}})
        rows = self._attach(db, self._rows(),
                            withhold=lambda row: row["snippet_id"] == "a")
        self.assertNotIn("practice_exercise", rows[0])
        self.assertEqual(rows[1]["practice_exercise"]["exercise_id"], "land")

    def test_a_finished_practice_ends_the_offer_on_its_moment_only(self):
        class _Done(self._Db):
            def get_confident_voice_practice_by_moment(self, _take, snip, owner=None):
                return ({"snippet_id": "a", "status": "completed"}
                        if snip == "a" else None)
        db = _Done({"a": {"insufficient_pauses": True},
                    "b": {"insufficient_pauses": True}, "c": {}})
        rows = self._attach(db, self._rows())
        self.assertNotIn("practice_exercise", rows[0])
        self.assertEqual(rows[1]["practice_exercise"]["exercise_id"], "land")


class ContractTests(unittest.TestCase):
    def test_the_contract_and_the_repo_rules_record_the_decision(self):
        contract = (ROOT / "docs/CANONICAL_PRODUCT_CONTRACT.md").read_text()
        self.assertIn("as many exercises as bookmark indicates", contract)
        self.assertIn("Your coach is working on your exercise.", contract)
        rules = (ROOT / "CLAUDE.md").read_text()
        self.assertNotIn("one exercise (on the weakest item", rules)
        self.assertIn("an exercise on any bookmark", rules)

    def test_the_migration_keys_practice_per_moment(self):
        manifest = (ROOT / "migrations/manifest.txt").read_text()
        self.assertIn("one_practice_per_moment.sql", manifest)
        sql = (ROOT / "migrations/one_practice_per_moment.sql").read_text()
        self.assertIn("DROP CONSTRAINT IF EXISTS confident_voice_practice_one_per_take", sql)
        self.assertIn("UNIQUE (take_session_id, snippet_id)", sql)
