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

import unittest

from services import confident_voice_practice as cvp
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


class EightyTwentyTests(unittest.TestCase):

    def test_the_legacy_lane_draws_too(self):
        db = _Db(snippet=_snippet(), assign=_pick(2))
        rows = cvp.attach_exercise_offer(
            [{"id": "x", "source": "confident_voice", "snippet_id": "s1"}],
            take_session_id="take-1", database=db, owner_user_id="owner-1")
        self.assertEqual(_offers(rows), {"x": "second"})
        self.assertEqual(db.assign_calls[0]["lane"], "legacy_offer")


    def test_no_number_about_the_draw_reaches_the_payload(self):
        rows = _attach_v3(_Db(assign=_pick(2)))
        offer = next(r["practice_exercise"] for r in rows if r["id"] == "a")
        for leaked in ("draw", "probability", "selected_rank", "selection_mode",
                       "candidates", "rank"):
            self.assertNotIn(leaked, offer)
