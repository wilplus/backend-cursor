"""A judgement is always answered (founder 2026-09-29): a No on a bookmark
with no exercise sends it to the coach when the answer is saved."""
from __future__ import annotations

import unittest
from unittest.mock import patch
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


def _verdict(read, fired):
    pattern = {"confident": "confident", "weak": "low_confidence_rushing_dominant",
               "unknown": None}[read]
    verdict = {"eligible": True, "pattern": pattern, "priority": 1,
               "signals": {"insufficient_pauses": True} if fired else {},
               "snapshot": {}}
    if pattern is None:
        verdict = {"eligible": False, "reason": "confidence_unavailable"}
    return verdict


def _judged(db, answer, *, read="weak", fired=False):
    """One judgement, with the machine's read and what fired pinned."""
    original = cvp.exercise_eligibility
    cvp.exercise_eligibility = lambda *_a, **_k: _verdict(read, fired)
    try:
        return _follow(db, answer)
    finally:
        cvp.exercise_eligibility = original


@patch("config.Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED", False)
class MatrixTests(unittest.TestCase):
    """The matrix on the judgement path (24f). Since 2026-10-02 the request
    rises at the open (24e-1) and the judgement sets answer_kind; these pin
    the kinds the judgement path records when F1 is off."""
    """The follow-up matrix (founder 2026-09-29), cell by cell."""

    def test_read_confident_is_praise_now_for_every_answer(self):
        for answer, kind in (("yes", "praise"), ("in_between", "praise"),
                             ("no", "ambiguity"), ("not_sure", "ambiguity")):
            db = _Db()
            self.assertEqual(_judged(db, answer, read="confident"), "praise", answer)
            self.assertEqual(db.raised[0]["kind"], kind, answer)

    def test_read_weak_with_a_problem_fired_is_the_video_lane(self):
        for answer, kind in (("in_between", "error"), ("no", "error"),
                             ("not_sure", "ambiguity")):
            db = _Db()
            self.assertEqual(_judged(db, answer, fired=True), "coach_request", answer)
            self.assertEqual(db.raised[0]["kind"], kind, answer)
            self.assertEqual(db.raised[0]["reason"], "nothing_targets_it")
        matched = _Db(assignment={"selected_exercise_id": "x"})
        self.assertEqual(_judged(matched, "no", fired=True), "exercise")
        self.assertEqual(matched.raised[0]["kind"], "error")
        self.assertEqual(matched.raised[0]["reason"], "library_matched")

    def test_read_weak_with_nothing_fired_is_the_rewrite(self):
        for answer, kind in (("in_between", "rewrite"), ("no", "rewrite"),
                             ("not_sure", "ambiguity")):
            db = _Db()
            self.assertEqual(_judged(db, answer), "rewrite", answer)
            self.assertEqual(db.raised[0]["kind"], kind, answer)
            self.assertEqual(db.raised[0]["reason"], "nothing_spotted")

    def test_a_yes_the_machine_reads_weak_shows_nothing_and_asks_the_coach(self):
        for fired in (True, False):
            db = _Db()
            self.assertEqual(_judged(db, "yes", fired=fired), "none")
            self.assertEqual(db.raised[0]["kind"], "ambiguity")

    def test_an_unreadable_clip_shows_nothing_and_asks_the_coach(self):
        db = _Db()
        self.assertEqual(_judged(db, "no", read="unknown"), "none")
        self.assertEqual(db.raised[0]["kind"], "ambiguity")

    def test_audio_unclear_raises_nothing(self):
        db = _Db()
        self.assertEqual(_judged(db, "audio_unclear", fired=True), "none")
        self.assertEqual(db.raised, [])

    def test_a_request_already_raised_is_not_raised_twice(self):
        db = _Db(request={"id": "req-1", "resolution": None, "kind": "error"})
        self.assertEqual(_judged(db, "no", fired=True), "coach_request")
        self.assertEqual(db.raised, [])

    def test_the_request_carries_the_trace_and_the_owner(self):
        db = _Db()
        _judged(db, "no", fired=True)
        raised = db.raised[0]
        self.assertEqual(raised["snippet_id"], "snip-1")
        self.assertEqual(raised["owner_user_id"], "owner-1")
        self.assertEqual(raised["request_trace"]["lane"], "v3_judgement")

    def test_a_failed_write_never_fails_the_answer(self):
        class _Broken(_Db):
            def request_exercise_from_coach(self, **_kwargs):
                raise RuntimeError("rpc down")
        # A failed write shows nothing rather than promising the coach.
        self.assertEqual(_judged(_Broken(), "no", fired=True), "none")
        self.assertEqual(_judged(_Broken(), "no", fired=False), "rewrite")

    def test_the_pure_matrix(self):
        from services.judgement_follow_up import decide
        self.assertEqual(decide("yes", "confident", True, False), ("praise", "praise"))
        self.assertEqual(decide("no", "confident", False, False), ("praise", "ambiguity"))
        self.assertEqual(decide("in_between", "weak", True, True), ("exercise", "error"))
        self.assertEqual(decide("no", "weak", True, False), ("coach_request", "error"))
        self.assertEqual(decide("not_sure", "weak", True, False), ("coach_request", "ambiguity"))
        self.assertEqual(decide("in_between", "weak", False, False), ("rewrite", "rewrite"))
        self.assertEqual(decide("yes", "weak", True, True), ("none", "ambiguity"))
        self.assertEqual(decide("no", "unknown", False, False), ("none", "ambiguity"))
        self.assertEqual(decide("audio_unclear", "weak", True, True), ("none", None))


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
        self.assertEqual(rows[0]["coach_request"], {"status": "open", "kind": "error"})
        self.assertNotIn("coach_request", rows[1])
        self.assertNotIn("coach_request", rows[2])

    def test_an_answered_unshared_request_reads_answered(self):
        db = self._Db({"a": {"id": "r", "resolution": "no_safe_match",
                             "shared_at": None}})
        rows = cvp._annotate_coach_answers(
            self._rows(), take_session_id="t", owner_user_id="o",
            database=db, ground=lambda _r: None)
        self.assertEqual(rows[0]["coach_request"], {"status": "answered", "kind": "error"})

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
        self.assertIn("follow_up_for_judgement(", route)
        self.assertIn('"follow_up": follow_up', route)
        # After the owner route is written, never before.
        self.assertLess(route.index("_route_owner_voice_album("),
                        route.index("follow_up_for_judgement("))


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

    def _attach(self, db, rows):
        original = cvp.exercise_eligibility
        cvp.exercise_eligibility = lambda snippet, **_k: {
            "eligible": True, "pattern": "low_confidence_rushing_dominant",
            "priority": 1, "signals": db.fired[snippet["id"]], "snapshot": {}}
        try:
            return cvp.attach_v3_exercise_offer(
                rows, take_session_id="take-1", owner_user_id="owner-1",
                database=db, ground=lambda _row: {"slide_index": 0})
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
        self.assertIn("follow-up matrix", contract)
        for kind in ("error", "praise", "rewrite", "ambiguity"):
            self.assertIn(kind, contract)
        rules = (ROOT / "CLAUDE.md").read_text()
        self.assertNotIn("one exercise (on the weakest item", rules)
        self.assertIn("an exercise on any bookmark", rules)

    def test_the_migration_keys_practice_per_moment(self):
        manifest = (ROOT / "migrations/manifest.txt").read_text()
        self.assertIn("0396\tone_practice_per_moment.sql", manifest)
        self.assertIn("0397\tevery_judgement_reaches_the_coach.sql", manifest)
        kinds = (ROOT / "migrations/every_judgement_reaches_the_coach.sql").read_text()
        self.assertIn("request_exercise_from_coach_v2", kinds)
        self.assertIn("'library_matched'", kinds)
        sql = (ROOT / "migrations/one_practice_per_moment.sql").read_text()
        self.assertIn("DROP CONSTRAINT IF EXISTS confident_voice_practice_one_per_take", sql)
        self.assertIn("UNIQUE (take_session_id, snippet_id)", sql)
