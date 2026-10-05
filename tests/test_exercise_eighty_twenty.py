"""The exercise reaches V3 Takes, chosen 80/20 (founder 2026-09-26).

Two decisions, pinned here:

  * "please do the 80/20 try smth new": a moment with two or more eligible
    exercises gets the best match 4 times in 5 and another eligible one
    otherwise, frozen once per moment (migration 0372; the draw itself is
    pinned in tests/test_exercise_assignment_postgres.py);
  * "Follow V3": the one Confident Voice item V3 marks `bookmark_tier =
    "exercise"` (contract 24f) carries the exercise. The rush gate no longer
    decides the moment there; the safety half of the gate still does.

And the defect that made both necessary: the offer was attached above
`_first_client_feedback`, which replaces the rows on every V3 Take, so no V3
Take ever carried an exercise.
"""
from __future__ import annotations

import ast
import inspect
import unittest

from services import confident_voice_practice as cvp
from services import ideal_text_changes as itc
from tests.test_confident_voice_practice import _snippet, _words


def _calm_snippet(**over):
    """Safe to practise on, but not enough rush evidence: the gate's last
    refusal. One problem is still spotted (too few pauses), because with
    nothing spotted no exercise is offered at all (D1, 2026-09-28)."""
    row = _snippet(words=_words(compressed=False), **over)
    # Read weak: the library video is for a clip the machine reads weak (the
    # follow-up matrix, founder 2026-09-29); a confident read is praise.
    row["metrics"] = {**row["metrics"], "pause_ratio": 0.05, "voiced_ratio": 0.6,
                      "voice_confidence": {**row["metrics"]["voice_confidence"],
                                           "score": -0.2}}
    return row


def _exercise(exercise_id, editorial=0):
    return {
        "exercise_id": exercise_id, "version": 1, "title": exercise_id,
        "instruction": "Do it.", "explanation_video_url": f"https://x/{exercise_id}.mp4",
        "supported_confidence_patterns": ["near_confident"],
        "acoustic_problem_tags": ["rushing"],
        "matching_criteria": {"editorial_priority": editorial},
    }


class _Db:
    def __init__(self, *, snippet=None, existing=None, assign=None,
                 exercises=("best", "second", "third")):
        self.snippet = snippet if snippet is not None else _calm_snippet(id="snip-v3")
        self.existing = existing
        self.catalogue = {
            eid: _exercise(eid, editorial=10 - i) for i, eid in enumerate(exercises)}
        self.assign_impl = assign
        self.assign_calls: list[dict] = []
        self.assignment = None

    def list_diagnostic_exercises(self):
        return [{"exercise_id": eid} for eid in self.catalogue]

    def get_active_diagnostic_exercise(self, exercise_id):
        return self.catalogue.get(exercise_id)

    def get_confident_voice_practice_by_take(self, _take):
        return self.existing

    def get_confident_voice_practice_candidates(self, ids):
        return [dict(self.snippet, id=i) for i in ids]

    def get_snippets_by_session(self, _take):
        return [{"metrics": {"wpm": 150.0}}]

    def assign_confident_voice_exercise(self, **kw):
        self.assign_calls.append(kw)
        if self.assign_impl is None:
            return None
        self.assignment = self.assign_impl(kw)
        return self.assignment

    def get_confident_voice_exercise_assignment(self, _take, _snippet):
        return self.assignment


def _v3_rows():
    return [
        {"id": "a", "source": "confident_voice", "feedback_family": "confident_voice",
         "snippet_id": "snip-v3", "bookmark_tier": "exercise",
         "span": {"start": 0, "end": 5}},
        {"id": "b", "source": "confident_voice", "feedback_family": "confident_voice",
         "snippet_id": "snip-other", "bookmark_tier": "most_confident",
         "span": {"start": 10, "end": 15}},
    ]


_EVIDENCE = {"project_id": "arc", "take_session_id": "take-1", "slide_index": 0,
             "paragraph_index": 0, "span": {"start": 0, "end": 5}}


def _attach_v3(db, *, ground=lambda row: dict(_EVIDENCE)):
    return cvp.attach_v3_exercise_offer(
        _v3_rows(), take_session_id="take-1", owner_user_id="owner-1",
        database=db, ground=ground)


def _offers(rows):
    return {row["id"]: row["practice_exercise"]["exercise_id"]
            for row in rows if "practice_exercise" in row}


def _pick(rank):
    def assign(kw):
        chosen = kw["candidates"][rank - 1]
        return {"id": "asg-1", "selected_exercise_id": chosen["exercise_id"],
                "selected_rank": rank,
                "selection_mode": "top" if rank == 1 else "exploration"}
    return assign


class V3ExerciseTests(unittest.TestCase):
    def test_every_bookmark_carries_the_exercise_matched_to_its_clip(self):
        # FOUNDER 2026-09-29: "they can carry as many exercises as bookmark
        # indicates". Until then only the item V3 marked for it carried one.
        rows = _attach_v3(_Db())
        self.assertEqual(_offers(rows), {"a": "best", "b": "best"})
        target = next(r for r in rows if r["id"] == "a")
        # The practice cannot start without exact evidence; V3 rows arrive
        # without it, so the lane grounds it.
        self.assertEqual(target["evidence"], _EVIDENCE)

    def test_the_rush_gate_does_not_decide_v3_s_moment(self):
        verdict = cvp.exercise_eligibility(_calm_snippet(), session_median_wpm=150)
        self.assertFalse(verdict["eligible"])
        self.assertEqual(verdict["reason"], "weak_acoustic_evidence")
        self.assertEqual(_offers(_attach_v3(_Db())), {"a": "best", "b": "best"})

    def test_a_clip_that_cannot_carry_practice_gets_none(self):
        unsafe = _snippet()
        unsafe["metrics"] = {**unsafe["metrics"],
                             "audio_quality": {"reliable": False, "noise_dominant": True}}
        self.assertEqual(_offers(_attach_v3(_Db(snippet=unsafe))), {})
        short = _snippet(transcript="Too short", words=[])
        self.assertEqual(_offers(_attach_v3(_Db(snippet=short))), {})

    def test_no_provable_evidence_means_no_exercise_and_no_draw(self):
        db = _Db(assign=_pick(1))
        self.assertEqual(_offers(_attach_v3(db, ground=lambda row: None)), {})
        self.assertEqual(db.assign_calls, [])

    def test_one_practice_per_moment(self):
        # A finished practice ends the offer on ITS moment only (2026-09-29);
        # another moment's practice on the same Take no longer blocks this one.
        done = _Db(existing={"id": "p", "snippet_id": "snip-v3", "status": "completed"})
        self.assertEqual(_offers(_attach_v3(done)), {"b": "best"})
        elsewhere = _Db(existing={"id": "p", "snippet_id": "snip-x", "status": "open"})
        self.assertEqual(_offers(_attach_v3(elsewhere)), {"a": "best", "b": "best"})
        resumed = _attach_v3(_Db(existing={
            "id": "p", "snippet_id": "snip-v3", "status": "open"}))
        offer = next(r["practice_exercise"] for r in resumed if r["id"] == "a")
        self.assertTrue(offer["resume"])

    def test_the_bookmark_tier_no_longer_decides_who_carries_one(self):
        rows = [dict(r, bookmark_tier="standard") for r in _v3_rows()]
        out = cvp.attach_v3_exercise_offer(
            rows, take_session_id="take-1", owner_user_id="o", database=_Db(),
            ground=lambda row: dict(_EVIDENCE))
        self.assertEqual(_offers(out), {"a": "best", "b": "best"})


class EightyTwentyTests(unittest.TestCase):
    def test_the_frozen_choice_is_what_is_served(self):
        db = _Db(assign=_pick(3))
        self.assertEqual(_offers(_attach_v3(db)), {"a": "third", "b": "third"})
        call = db.assign_calls[0]
        self.assertEqual([c["exercise_id"] for c in call["candidates"]],
                         ["best", "second", "third"])
        self.assertEqual((call["lane"], call["owner_user_id"], call["snippet_id"]),
                         ("v3_exercise_block", "owner-1", "snip-v3"))

    def test_the_legacy_lane_draws_too(self):
        db = _Db(snippet=_snippet(), assign=_pick(2))
        rows = cvp.attach_exercise_offer(
            [{"id": "x", "source": "confident_voice", "snippet_id": "s1"}],
            take_session_id="take-1", database=db, owner_user_id="owner-1")
        self.assertEqual(_offers(rows), {"x": "second"})
        self.assertEqual(db.assign_calls[0]["lane"], "legacy_offer")

    def test_without_the_table_the_best_match_is_served_as_before(self):
        class Unmigrated(_Db):
            def assign_confident_voice_exercise(self, **kw):
                raise RuntimeError("function does not exist")
        self.assertEqual(_offers(_attach_v3(Unmigrated())), {"a": "best", "b": "best"})

    def test_a_frozen_choice_that_left_the_catalogue_is_not_swapped(self):
        db = _Db(assign=lambda kw: {"id": "asg", "selected_exercise_id": "retired"})
        self.assertEqual(_offers(_attach_v3(db)), {})

    def test_no_number_about_the_draw_reaches_the_payload(self):
        rows = _attach_v3(_Db(assign=_pick(2)))
        offer = next(r["practice_exercise"] for r in rows if r["id"] == "a")
        for leaked in ("draw", "probability", "selected_rank", "selection_mode",
                       "candidates", "rank"):
            self.assertNotIn(leaked, offer)


class StartCheckTests(unittest.TestCase):
    def _check(self, db, exercise_id, snippet=None):
        return cvp.start_exercise_check(
            snippet=snippet or _calm_snippet(), take_session_id="take-1",
            snippet_id="snip-v3", exercise_id=exercise_id,
            session_median_wpm=150, database=db)

    def test_the_assigned_exercise_starts_even_without_rush_evidence(self):
        db = _Db()
        db.assignment = {"id": "asg-9", "selected_exercise_id": "third"}
        refusal, _, matching = self._check(db, "third")
        self.assertIsNone(refusal)
        self.assertEqual(matching["exercise_assignment_id"], "asg-9")
        self.assertEqual(matching["exposure_policy_version"], "exercise-80-20-v1")

    def test_any_other_exercise_is_stale(self):
        db = _Db()
        db.assignment = {"id": "asg-9", "selected_exercise_id": "third"}
        self.assertEqual(self._check(db, "best")[0], "EXERCISE_OFFER_STALE")

    def test_an_unsafe_clip_is_refused_even_with_an_assignment(self):
        db = _Db()
        db.assignment = {"id": "asg-9", "selected_exercise_id": "best"}
        unsafe = _snippet()
        unsafe["metrics"] = {**unsafe["metrics"],
                             "audio_quality": {"reliable": False, "noise_dominant": True}}
        self.assertEqual(self._check(db, "best", unsafe)[0], "NOT_ELIGIBLE")

    def test_without_an_assignment_the_old_rule_holds(self):
        db = _Db()
        self.assertEqual(self._check(db, "best")[0], "NOT_ELIGIBLE")
        refusal, _, matching = self._check(db, "best", _snippet())
        self.assertIsNone(refusal)
        self.assertNotIn("exercise_assignment_id", matching)


class PipelineOrderTests(unittest.TestCase):
    """The offer must run after V3 replaces the rows, and after the claim."""

    def _calls(self):
        import textwrap
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(itc._ChangesRun.execute)))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "run" and len(node.args) > 1 \
                        and isinstance(node.args[1], ast.Attribute):
                    found.append((node.lineno, node.args[1].attr))
                elif isinstance(node.func.value, ast.Name) \
                        and node.func.value.id == "self":
                    found.append((node.lineno, node.func.attr))
        return [name for _, name in sorted(found)]

    def test_the_offer_follows_the_v3_replacement_and_the_claim(self):
        calls = self._calls()
        self.assertLess(calls.index("_first_client_feedback"),
                        calls.index("_practice_offer"))
        self.assertLess(calls.index("_claim_visibly"),
                        calls.index("_practice_offer"))

    def test_a_v3_take_takes_the_v3_lane(self):
        run = itc._ChangesRun.__new__(itc._ChangesRun)
        run.changes = ["v3-row"]
        run.v3_replaced_changes = True
        run._practice_permitted = lambda: True
        taken = []
        run._v3_exercise_offer = lambda: taken.append("v3")
        run._practice_offer()
        self.assertEqual(taken, ["v3"])


class EveryMomentCanBePractisedTests(unittest.TestCase):
    """F1 Repair Plan Phase 4 (founder lock 2026-09-30, B6): the practice
    cannot start without the moment's evidence coordinates, which only the
    exercise steps used to ground. A praise moment -- read confident, so no
    library video -- recorded and then went nowhere."""

    def _confident(self):
        row = _snippet(id="snip-v3")
        row["metrics"] = {**row["metrics"], "voice_confidence": {
            **row["metrics"]["voice_confidence"], "score": 0.9}}
        return row

    def test_a_praise_moment_is_grounded_without_an_exercise(self):
        rows = _attach_v3(_Db(snippet=self._confident()))
        self.assertEqual(_offers(rows), {})
        for row in rows:
            self.assertEqual(row["evidence"], _EVIDENCE)

    def test_a_moment_ground_cannot_prove_is_served_as_it_was(self):
        rows = _attach_v3(_Db(snippet=self._confident()), ground=lambda row: None)
        self.assertTrue(all("evidence" not in row for row in rows))

    def test_a_failing_ground_never_loses_the_item(self):
        def boom(_row):
            raise RuntimeError("no pieces")
        rows = cvp._ground_every_moment(
            [{"id": "a", "source": "confident_voice", "snippet_id": "s"}],
            ground=boom)
        self.assertEqual(rows, [{"id": "a", "source": "confident_voice",
                                 "snippet_id": "s"}])

    def test_only_confident_voice_moments_with_a_clip_are_grounded(self):
        rows = cvp._ground_every_moment(
            [{"id": "r", "source": "wording", "snippet_id": "s"},
             {"id": "c", "source": "confident_voice"}],
            ground=lambda row: dict(_EVIDENCE))
        self.assertTrue(all("evidence" not in row for row in rows))

    def test_an_exercise_moment_keeps_its_own_coordinates(self):
        own = {"project_id": "arc", "span": {"start": 1, "end": 2}}
        rows = cvp._ground_every_moment(
            [{"id": "a", "source": "confident_voice", "snippet_id": "s",
              "evidence": own}],
            ground=lambda row: dict(_EVIDENCE))
        self.assertIs(rows[0]["evidence"], own)
