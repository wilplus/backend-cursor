"""A coach hears when no exercise fits (founder 2026-09-28; contract 35b/35f).

Pins:
  * a bookmark with no fitting exercise records one coach request when the
    speaker's judgement is saved (founder 2026-09-29; until then V3's one
    exercise item did, at read time), with why (nothing spotted / nothing
    targets what was spotted), and the item is still served now — nobody
    waits on the coach;
  * a request that can't be written never costs the feedback;
  * an exercise the coach SHARED for that exact moment is what the item then
    carries, and the practice can start on it; one not shared, or edited
    since, is not served;
  * the coach resolves once, only after their blind rating, and only an
    exercise can be shared.
"""
from __future__ import annotations

import pathlib
import unittest

from services import confident_voice_practice as cvp
from services import exercise_coach_requests as ecr
from services.judgement_follow_up import follow_up_for_judgement
from tests.test_confident_voice_practice import V3ExerciseFitTests, _snippet

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Db(V3ExerciseFitTests._Db):
    def __init__(self, rows, *, request=None, fail=False):
        super().__init__(rows, {})
        self.request = request
        self.fail = fail
        self.requested = []
        self.resolved = []
        self.saved = []

    def request_exercise_from_coach(self, **kwargs):
        if self.fail:
            raise RuntimeError("function does not exist")
        self.requested.append(kwargs)
        return self.request or {"id": "req-1", **kwargs, "shared_at": None}

    def get_exercise_coach_request(self, _take, _snippet):
        return self.request

    def get_confident_voice_exercise_assignment(self, _take, _snippet):
        # The draw the read froze, as the RPC would return it.
        return ({"selected_exercise_id": self.assigned[-1]["candidates"][0]["exercise_id"]}
                if self.assigned else None)

    def resolve_exercise_coach_request(self, **kwargs):
        self.resolved.append(kwargs)
        if isinstance(self.request, dict) and self.request.get("resolution"):
            raise RuntimeError("EXERCISE_COACH_REQUEST_ALREADY_RESOLVED")
        return {**(self.request or {}), "resolution": kwargs["resolution"],
                "resolved_exercise_id": kwargs["exercise_id"],
                "shared_at": "now" if kwargs["share"] else None}

    def upsert_diagnostic_exercise(self, row):
        self.saved.append(row)
        return {**row, "version": row.get("version", 1)}


def _row(exercise_id, tags, primary=None):
    return V3ExerciseFitTests._row(None, exercise_id, tags, primary)


def _offer(db, fired):
    return V3ExerciseFitTests._offer(None, db, fired)


def _judge(db, fired, answer="no"):
    """The speaker's judgement on the moment, with these signals fired."""
    verdict = {"eligible": True, "pattern": "near_confident", "priority": 3,
               "signals": fired, "snapshot": {}}
    original = cvp.exercise_eligibility
    cvp.exercise_eligibility = lambda *_a, **_k: verdict
    try:
        return follow_up_for_judgement(
            db, take_session_id="take-1", snippet_id="snippet-a",
            owner_user_id="owner-1", answer=answer)
    finally:
        cvp.exercise_eligibility = original


def _shared(exercise_id="coach-pick", version=1):
    return {"id": "req-1", "take_session_id": "take-1",
            "snippet_id": "snippet-a", "reason": "nothing_targets_it",
            "observed_tags": ["rushing"], "resolution": "exercise_chosen",
            "resolved_exercise_id": exercise_id,
            "resolved_exercise_version": version, "shared_at": "2026-09-28"}


class RequestTests(unittest.TestCase):
    def test_nothing_targets_what_fired_records_a_request_on_the_judgement(self):
        db = _Db([_row("elsewhere", ["ending_compression"])])
        # The read serves the item now, writes nothing, and says a problem
        # was recognised so the sheet knows the judgement will send it.
        self.assertIsNone(_offer(db, {"insufficient_pauses": True}))
        self.assertEqual(db.requested, [])
        self.assertEqual(_judge(db, {"insufficient_pauses": True}), "coach_request")
        self.assertEqual(len(db.requested), 1)
        call = db.requested[0]
        self.assertEqual(call["reason"], "nothing_targets_it")
        self.assertEqual(call["observed_tags"], ["rushing"])
        self.assertEqual(call["snippet_id"], "snippet-a")
        self.assertEqual(call["request_trace"]["candidates"][0]["reason"],
                         "targets_nothing_that_fired")
        self.assertEqual(db.assigned, [])

    def test_nothing_spotted_records_why_on_a_no(self):
        db = _Db([_row("any", ["rushing"])])
        self.assertIsNone(_offer(db, {}))
        self.assertEqual(_judge(db, {}), "coach_request")
        self.assertEqual(db.requested[0]["reason"], "nothing_spotted")

    def test_nothing_spotted_stays_quiet_on_the_other_answers(self):
        for answer in ("yes", "in_between", "not_sure"):
            db = _Db([_row("any", ["rushing"])])
            self.assertEqual(_judge(db, {}, answer), "none", answer)
            self.assertEqual(db.requested, [])

    def test_a_recognised_problem_reaches_the_coach_on_any_answer_but_unclear(self):
        for answer in ("yes", "in_between", "not_sure", "no"):
            db = _Db([_row("elsewhere", ["ending_compression"])])
            self.assertEqual(_judge(db, {"insufficient_pauses": True}, answer),
                             "coach_request", answer)
        db = _Db([_row("elsewhere", ["ending_compression"])])
        self.assertEqual(_judge(db, {"insufficient_pauses": True}, "audio_unclear"),
                         "none")
        self.assertEqual(db.requested, [])

    def test_an_empty_library_still_reaches_the_coach(self):
        db = _Db([])
        _judge(db, {"insufficient_pauses": True})
        self.assertEqual(db.requested[0]["reason"], "nothing_targets_it")

    def test_a_request_that_cannot_be_written_never_costs_the_answer(self):
        db = _Db([], fail=True)
        self.assertIsNone(_offer(db, {"insufficient_pauses": True}))
        self.assertEqual(_judge(db, {"insufficient_pauses": True}), "none")

    def test_a_matched_moment_makes_no_request(self):
        db = _Db([_row("exact", ["rushing"])])
        self.assertIsNotNone(_offer(db, {"insufficient_pauses": True}))
        self.assertEqual(_judge(db, {"insufficient_pauses": True}), "exercise")
        self.assertEqual(db.requested, [])


class SharedExerciseTests(unittest.TestCase):
    def test_a_shared_exercise_rides_on_that_item(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request=_shared())
        offer = _offer(db, {"insufficient_pauses": True})
        self.assertEqual(offer["exercise_id"], "coach-pick")
        self.assertTrue(offer["chosen_by_coach"])
        self.assertEqual(offer["matching_policy_version"],
                         cvp.COACH_REQUEST_POLICY_VERSION)
        self.assertIsNone(offer["pattern_distance"])

    def test_a_resolution_not_yet_shared_is_not_served(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request={**_shared(), "shared_at": None})
        self.assertIsNone(_offer(db, {"insufficient_pauses": True}))

    def test_an_exercise_edited_since_the_share_is_not_served(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request=_shared(version=2))
        self.assertIsNone(_offer(db, {"insufficient_pauses": True}))

    def test_the_practice_can_start_on_the_shared_exercise(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request=_shared())
        refusal, _, matching = cvp.start_exercise_check(
            snippet=_snippet(id="snippet-a"), take_session_id="take-1",
            snippet_id="snippet-a", exercise_id="coach-pick",
            session_median_wpm=150, database=db)
        self.assertIsNone(refusal)
        self.assertEqual(matching["exercise_coach_request_id"], "req-1")
        self.assertEqual(matching["matching_policy_version"],
                         cvp.COACH_REQUEST_POLICY_VERSION)

    def test_a_different_exercise_is_not_let_in_by_the_share(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request=_shared())
        refusal, _, _ = cvp.start_exercise_check(
            snippet=_snippet(id="snippet-a"), take_session_id="take-1",
            snippet_id="snippet-a", exercise_id="something-else",
            session_median_wpm=150, database=db)
        self.assertIsNotNone(refusal)


class CoachResolutionTests(unittest.TestCase):
    def _open(self):
        return {"id": "req-1", "take_session_id": "take-1",
                "snippet_id": "snippet-a", "reason": "nothing_targets_it",
                "pattern": "near_confident", "observed_tags": ["rushing"],
                "request_trace": {"signals": {"insufficient_pauses": True}},
                "resolution": None, "shared_at": None}

    def _review(self, db, method="PUT", body=None):
        return ecr.review(db, take_session_id="take-1",
                          snippet_id="snippet-a", method=method, body=body,
                          coach_id="coach-1")

    def test_no_request_is_a_404(self):
        status, _ = self._review(_Db([]), "GET")
        self.assertEqual(status, 404)

    def test_the_coach_sees_what_was_spotted_by_its_library_name(self):
        db = _Db([_row("a", ["rushing"])], request=self._open())
        db.list_speaking_errors = lambda: [
            {"error_id": "rushing", "label": "Rushing", "status": "detected"}]
        status, payload = self._review(db, "GET")
        self.assertEqual(status, 200)
        self.assertEqual(payload["request"]["spotted"],
                         [{"error_id": "rushing", "label": "Rushing"}])
        self.assertEqual(payload["request"]["available_exercises"][0]
                         ["exercise_id"], "a")

    def test_choosing_and_sharing_an_exercise(self):
        db = _Db([_row("a", ["ending_compression"])], request=self._open())
        status, _ = self._review(db, body={
            "resolution": "exercise_chosen", "exercise_id": "a",
            "share_with_user": True})
        self.assertEqual(status, 200)
        self.assertEqual(db.resolved[0]["exercise_id"], "a")
        self.assertTrue(db.resolved[0]["share"])

    def test_an_inactive_exercise_cannot_be_chosen(self):
        db = _Db([], request=self._open())
        status, payload = self._review(db, body={
            "resolution": "exercise_chosen", "exercise_id": "gone"})
        self.assertEqual((status, payload["code"]), (409, "EXERCISE_UNAVAILABLE"))
        self.assertEqual(db.resolved, [])

    def test_no_safe_match_cannot_be_shared(self):
        db = _Db([], request=self._open())
        status, _ = self._review(db, body={
            "resolution": "no_safe_match", "share_with_user": True})
        self.assertEqual(status, 400)
        self.assertEqual(db.resolved, [])

    def test_an_authored_exercise_is_filed_for_what_was_spotted(self):
        db = _Db([], request=self._open())
        status, _ = self._review(db, body={
            "resolution": "exercise_authored",
            "custom_exercise": {"title": "Room to breathe",
                                "explanation_video_url": "https://x/v.mp4"}})
        self.assertEqual(status, 200)
        self.assertEqual(db.saved[0]["exercise_id"], "coach-request-req-1")
        self.assertEqual(db.saved[0]["acoustic_problem_tags"], ["rushing"])
        self.assertEqual(db.resolved[0]["resolution"], "exercise_authored")

    def test_an_authored_exercise_the_catalogue_refuses_is_explained(self):
        db = _Db([], request=self._open())
        status, payload = self._review(db, body={
            "resolution": "exercise_authored",
            "custom_exercise": {"title": "No video"}})
        self.assertEqual(status, 400)
        self.assertIn("video", payload["error"])
        self.assertEqual(db.resolved, [])

    def test_a_second_different_answer_is_refused_by_name(self):
        db = _Db([_row("a", ["rushing"])],
                 request={**self._open(), "resolution": "no_safe_match"})
        status, payload = self._review(db, body={
            "resolution": "exercise_chosen", "exercise_id": "a"})
        self.assertEqual((status, payload["code"]),
                         (409, "EXERCISE_COACH_REQUEST_ALREADY_RESOLVED"))

    def test_an_unknown_resolution_is_refused(self):
        status, _ = self._review(_Db([], request=self._open()),
                                 body={"resolution": "maybe"})
        self.assertEqual(status, 400)


class RouteTests(unittest.TestCase):
    def test_the_request_is_behind_the_blind_gate_and_the_speaker_s_yes(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_exercise_request")
        route = source[start:source.index("@v2_bp.route", start)]
        gate = route.index("BLIND_RATING_REQUIRED")
        self.assertLess(gate, route.index("review("))
        self.assertLess(route.index("_speaker_practice_permitted"),
                        route.index("review("))
        head = source[source.rindex("@v2_bp.route", 0, start):start]
        self.assertIn(
            '@operational_purpose_disabled("personalized_exercise_recommendation")',
            head)
