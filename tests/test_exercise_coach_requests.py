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
    verdict = {"eligible": True, "pattern": "low_confidence_rushing_dominant",
               "priority": 1, "signals": fired, "snapshot": {}}
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

    def test_nothing_spotted_on_a_no_is_a_rewrite_that_reaches_the_coach(self):
        db = _Db([_row("any", ["rushing"])])
        self.assertIsNone(_offer(db, {}))
        self.assertEqual(_judge(db, {}), "rewrite")
        self.assertEqual(db.requested[0]["reason"], "nothing_spotted")
        self.assertEqual(db.requested[0]["kind"], "rewrite")

    def test_every_answer_but_unclear_reaches_the_coach_with_its_kind(self):
        # The follow-up matrix (founder 2026-09-29): a weak read with nothing
        # fired is a rewrite (or an ambiguity on Not sure); with a problem
        # fired, an error (or an ambiguity); Audio unclear raises nothing.
        for answer, kind in (("yes", "ambiguity"), ("in_between", "rewrite"),
                             ("not_sure", "ambiguity"), ("no", "rewrite")):
            db = _Db([_row("any", ["rushing"])])
            _judge(db, {}, answer)
            self.assertEqual(db.requested[0]["kind"], kind, answer)
        for answer, kind in (("yes", "ambiguity"), ("in_between", "error"),
                             ("not_sure", "ambiguity"), ("no", "error")):
            db = _Db([_row("elsewhere", ["ending_compression"])])
            _judge(db, {"insufficient_pauses": True}, answer)
            self.assertEqual(db.requested[0]["kind"], kind, answer)
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
        # And never promises the coach: nothing shows instead of the sentence.
        self.assertEqual(_judge(db, {"insufficient_pauses": True}), "none")

    def test_a_matched_moment_still_reaches_the_coach_as_an_error(self):
        # The library video shows now; the coach may add their own on top.
        db = _Db([_row("exact", ["rushing"])])
        self.assertIsNotNone(_offer(db, {"insufficient_pauses": True}))
        self.assertEqual(_judge(db, {"insufficient_pauses": True}), "exercise")
        self.assertEqual(db.requested[0]["kind"], "error")
        self.assertEqual(db.requested[0]["reason"], "library_matched")


class SharedExerciseTests(unittest.TestCase):
    def test_a_shared_exercise_rides_on_that_item(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request=_shared())
        offer = _offer(db, {"insufficient_pauses": True})
        self.assertEqual(offer["exercise_id"], "coach-pick")
        self.assertTrue(offer["chosen_by_coach"])
        self.assertNotIn("matching_policy_version", offer)
        self.assertNotIn("pattern_distance", offer)

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
                                "main_target": "rushing",
                                "explanation_video_url": "https://x/v.mp4"}})
        self.assertEqual(status, 200)
        self.assertEqual(db.saved[0]["exercise_id"], "coach-request-req-1")
        self.assertEqual(db.saved[0]["acoustic_problem_tags"], ["rushing"])
        self.assertEqual(db.resolved[0]["resolution"], "exercise_authored")

    def test_an_authored_exercise_the_catalogue_refuses_is_explained(self):
        db = _Db([], request=self._open())
        status, payload = self._review(db, body={
            "resolution": "exercise_authored",
            "custom_exercise": {"title": "No video", "main_target": "rushing"}})
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


# ── THE COACH'S PICK COUNTS (founder 2026-09-29, decision 3; 0398) ────────
#
# A coach-shared exercise gets the same rows a machine pick gets, under the
# coach policy name: an assignment and a trace when it is first served, the
# render receipt when the card is on screen, and the practice links to that
# assignment. Nothing about the coach's choice is folded into the draw.


class _CountingDb(_Db):
    def __init__(self, rows, *, request=None, fail_assign=False):
        super().__init__(rows, request=request)
        self.coach_assigned = []
        self.fail_assign = fail_assign

    def assign_coach_shared_exercise(self, **kwargs):
        if self.fail_assign:
            raise RuntimeError("PGRST202 function not found")
        self.coach_assigned.append(kwargs)
        return {"id": f"coach-asg-{len(self.coach_assigned)}", **kwargs,
                "selected_exercise_id": kwargs["exercise_id"]}

    def get_coach_shared_exercise_assignment(self, _take, _snippet):
        if not self.coach_assigned:
            return None
        last = self.coach_assigned[-1]
        return {"id": f"coach-asg-{len(self.coach_assigned)}",
                "selected_exercise_id": last["exercise_id"],
                "exposure_policy_version": "exercise-coach-shared-v1"}


class CoachPickCountsTests(unittest.TestCase):
    def test_a_served_share_freezes_one_coach_assignment_with_its_trace(self):
        db = _CountingDb([_row("coach-pick", ["ending_compression"])],
                         request=_shared())
        offer = _offer(db, {"insufficient_pauses": True})
        _offer(db, {"insufficient_pauses": True})   # a second poll

        self.assertTrue(offer["chosen_by_coach"])
        self.assertEqual(len(db.coach_assigned), 2)   # insert-once in the db
        frozen = db.coach_assigned[0]
        self.assertEqual(frozen["lane"], "coach_request")
        self.assertEqual(frozen["matching_policy_version"],
                         cvp.COACH_REQUEST_POLICY_VERSION)
        self.assertEqual(frozen["exercise_id"], "coach-pick")
        self.assertEqual(frozen["exercise_version"], 1)
        trace = frozen["trace"]
        self.assertEqual(trace["trace_schema"], cvp.MATCH_TRACE_SCHEMA)
        self.assertIsNone(trace["fit"])
        self.assertEqual(trace["source_id"], "req-1")
        self.assertEqual(len(trace["candidates"]), 1)
        candidate = trace["candidates"][0]
        self.assertEqual(candidate["outcome"], "coach_chosen")
        self.assertEqual(candidate["exercise_id"], "coach-pick")
        self.assertEqual(candidate["main_targets"], ["ending_compression"])
        self.assertEqual(trace["observed_tags"], ["rushing"])

    def test_the_speaker_s_payload_is_unchanged_by_the_freeze(self):
        db = _CountingDb([_row("coach-pick", ["ending_compression"])],
                         request=_shared())
        offer = _offer(db, {"insufficient_pauses": True})
        for key in ("exercise_assignment_id", "matching_policy_version",
                    "exposure_policy_version", "pattern_distance",
                    "selection_mode", "lane"):
            self.assertNotIn(key, offer)

    def test_a_freeze_that_fails_still_serves_the_coach_s_exercise(self):
        db = _CountingDb([_row("coach-pick", ["ending_compression"])],
                         request=_shared(), fail_assign=True)
        offer = _offer(db, {"insufficient_pauses": True})
        self.assertEqual(offer["exercise_id"], "coach-pick")
        self.assertTrue(offer["chosen_by_coach"])

    def test_the_practice_links_to_the_coach_assignment(self):
        db = _CountingDb([_row("coach-pick", ["ending_compression"])],
                         request=_shared())
        _offer(db, {"insufficient_pauses": True})
        refusal, _, matching = cvp.start_exercise_check(
            snippet=_snippet(id="snippet-a"), take_session_id="take-1",
            snippet_id="snippet-a", exercise_id="coach-pick",
            session_median_wpm=150, database=db)
        self.assertIsNone(refusal)
        self.assertEqual(matching["exercise_assignment_id"], "coach-asg-1")
        self.assertEqual(matching["exercise_coach_request_id"], "req-1")

    def test_without_0398_the_practice_starts_as_before(self):
        db = _Db([_row("coach-pick", ["ending_compression"])],
                 request=_shared())
        refusal, _, matching = cvp.start_exercise_check(
            snippet=_snippet(id="snippet-a"), take_session_id="take-1",
            snippet_id="snippet-a", exercise_id="coach-pick",
            session_median_wpm=150, database=db)
        self.assertIsNone(refusal)
        self.assertNotIn("exercise_assignment_id", matching)

    def test_the_review_share_is_frozen_from_the_practice_s_own_evidence(self):
        db = _CountingDb([_row("coach-pick", ["ending_compression"])])
        practice = {"id": "practice-9", "owner_user_id": "owner-1",
                    "take_session_id": "take-1", "snippet_id": "snippet-a",
                    "acoustic_evidence": {"signals": {"insufficient_pauses": True}},
                    "machine_assessment": {"pattern": "near_confident"}}
        row = cvp.record_coach_review_share(
            db, practice, _row("coach-pick", ["ending_compression"]))
        self.assertEqual(row["id"], "coach-asg-1")
        frozen = db.coach_assigned[0]
        self.assertEqual(frozen["lane"], "coach_review")
        self.assertEqual(frozen["matching_policy_version"],
                         cvp.COACH_REVIEW_POLICY_VERSION)
        self.assertEqual(frozen["trace"]["source_id"], "practice-9")
        self.assertEqual(frozen["trace"]["observed_tags"], ["rushing"])
        self.assertEqual(frozen["trace"]["pattern"], "near_confident")

    def test_the_review_route_freezes_the_share_and_carries_the_id(self):
        route = (ROOT / "routes" / "v2" / "coach.py").read_text()
        # The freeze lives in the snapshot helper (the route is fenced and
        # may only shrink); the route hands it the practice only on a share.
        helper = route[route.index("def _shared_exercise_snapshot"):]
        helper = helper[:helper.index("def v2_coach_confident_voice_practice")]
        self.assertIn("record_coach_review_share(db, practice, exercise)", helper)
        self.assertIn('snapshot["exercise_assignment_id"]', helper)
        block = route[route.index("def v2_coach_confident_voice_practice"):]
        block = block[:block.index("def v2_coach_exercise_request")]
        self.assertIn("practice if share else None", block)
        # Frozen only on a share, and before the snapshot is saved.
        self.assertLess(block.index("practice if share else None"),
                        block.index("patch = {"))


class CoachOnPanelTests(unittest.TestCase):
    """The promise needs a coach (founder 2026-09-30, cold start; P1-3)."""

    def setUp(self):
        cvp._coach_presence = (0.0, None)

    def _rows(self, db):
        rows = [{"source": "confident_voice", "snippet_id": "snippet-a"}]
        return cvp._annotate_coach_answers(
            rows, take_session_id="take-1", owner_user_id="owner",
            database=db, ground=lambda _row: None)

    def test_no_coach_means_no_sentence_but_the_request_stays(self):
        db = _Db([], request={"id": "req-1", "kind": "error",
                              "resolution": None, "shared_at": None})
        db.any_active_coach = lambda: False
        self.assertNotIn("coach_request", self._rows(db)[0])
        # The request row itself is untouched: a coach who joins finds it.
        self.assertIsNotNone(db.get_exercise_coach_request("take-1", "snippet-a"))

    def test_a_coach_on_the_panel_keeps_the_sentence(self):
        db = _Db([], request={"id": "req-1", "kind": "error",
                              "resolution": None, "shared_at": None})
        db.any_active_coach = lambda: True
        self.assertEqual(self._rows(db)[0]["coach_request"],
                         {"status": "open", "kind": "error"})

    def test_a_database_that_cannot_say_keeps_todays_behaviour(self):
        db = _Db([], request={"id": "req-1", "kind": "error",
                              "resolution": None, "shared_at": None})
        # No helper at all (older fakes), and a helper that fails: both
        # keep the sentence rather than hide a real coach's work.
        self.assertIn("coach_request", self._rows(db)[0])
        db.any_active_coach = lambda: None
        cvp._coach_presence = (0.0, None)
        self.assertIn("coach_request", self._rows(db)[0])

    def test_the_read_is_cached_for_a_minute(self):
        calls = []

        class _Coachless:
            def any_active_coach(self):
                calls.append(1)
                return False
        self.assertFalse(cvp.coach_on_panel(_Coachless(), now=100.0))
        self.assertFalse(cvp.coach_on_panel(_Coachless(), now=130.0))
        self.assertEqual(len(calls), 1)
        self.assertFalse(cvp.coach_on_panel(_Coachless(), now=100.0 + 61))
        self.assertEqual(len(calls), 2)
