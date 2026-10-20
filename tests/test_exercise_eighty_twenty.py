"""
STORY    As a speaker, I want a moment I can improve to carry one exercise,
         usually the best match and sometimes another, so that I get a fitting
         practice and the product keeps learning.
OUTCOME
  O1  A Confident Voice moment read weak carries the exercise the 80/20 draw
      chose; a moment read confident is praise and carries none.
  O2  Never-1: no draw number, rank or probability reaches the speaker's offer.
  O3  The older, non-V3 lane offers what the same draw chose.
PROVES   O1 -> test_a_weak_moment_carries_the_drawn_exercise_and_praise_none
         O2 -> test_a_weak_moment_carries_the_drawn_exercise_and_praise_none
         O3 -> test_the_legacy_lane_draws_too
WHY      Founder 2026-09-26 "please do the 80/20 try smth new"; 2026-09-29
         every bookmark may carry an exercise, a confident read is praise.
         The draw itself is pinned in tests/test_exercise_assignment_postgres.py.
"""
from __future__ import annotations

import unittest

from services import confident_voice_practice as cvp


def _words(*, compressed: bool) -> list[dict]:
    out, at = [], 0.0
    for index, token in enumerate(
        "read the same exact passage and give every single word enough space now".split()
    ):
        duration = 0.12 if compressed and index >= 8 else 0.24
        out.append({"word": token, "start": at, "end": at + duration})
        at += duration + (0.025 if compressed else 0.12)
    return out


def _snippet(**over) -> dict:
    """A rushed, compressed reading of a clean passage."""
    row = {
        "id": "snippet-a",
        "transcript": "Read the same exact passage and give every single word enough space now.",
        "duration_ms": 5000,
        "audio_segment_path": "snippets/a.webm",
        "words": _words(compressed=True),
        "metrics": {
            "wpm": 210.0, "pause_ratio": 0.03, "voiced_ratio": 0.78,
            "audio_quality": {"reliable": True, "noise_dominant": False},
            "voice_confidence": {"version": "voice-confidence-universal-v3",
                                 "score": 0.25},
        },
    }
    row.update(over)
    return row


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


def _confident_snippet(**over):
    """A clip the machine reads confident: praise, never a library video."""
    row = _calm_snippet(**over)
    row["metrics"]["voice_confidence"] = {
        **row["metrics"]["voice_confidence"], "score": 0.8}
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
                 exercises=("best", "second", "third"), confident_ids=()):
        self.snippet = snippet if snippet is not None else _calm_snippet(id="snip-v3")
        self.confident_ids = set(confident_ids)
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
        return [_confident_snippet(id=i) if i in self.confident_ids
                else dict(self.snippet, id=i) for i in ids]

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

    def test_a_weak_moment_carries_the_drawn_exercise_and_praise_none(self):
        rows = _attach_v3(_Db(assign=_pick(2), confident_ids={"snip-other"}))
        # The draw chose the second-best match ("something new"); the moment
        # read confident ("b") is praise and carries no exercise.
        self.assertEqual(_offers(rows), {"a": "second"})
        offer = next(r["practice_exercise"] for r in rows if r["id"] == "a")
        for leaked in ("draw", "probability", "selected_rank", "selection_mode",
                       "candidates", "rank"):
            self.assertNotIn(leaked, offer)
