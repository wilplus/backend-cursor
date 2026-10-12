"""Judgement after feedback (founder 2026-10-01, F1; Phase 2 of the
after-practice paths). On since 2026-10-02; the switch and its off-branch
were deleted 2026-10-11.

F1: "Opening a bookmark never asks for a judgment first. The machine's read
chooses the feedback. The speaker judges themselves after it: on a confident
moment right after the praise, on a moment that needed work after each
practice attempt. Helper words open on Yes or In-between of that judgment."

Pins: the open raises the moment's request under the machine's kind
(insert-once, raised at the open), the later judgement sets its answer_kind
from the matrix, a practice judgement that disagrees with the machine's
read of the attempt makes it an ambiguity, no read and Audio unclear send
nothing, the practice may start without an answer, a landed or dismissed
practice or a skipped bookmark settles the item without a Path 1 answer,
and the coach reads the speaker's side only after the blind rating.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import confident_voice_practice as cvp
from services import judgement_follow_up as jf


def _snippet():
    return {"id": "snip-1", "transcript": "we think the timing matters here",
            "duration_ms": 4000, "audio_segment_path": "s/1.webm", "words": [],
            "metrics": {"wpm": 150.0, "pause_ratio": 0.1, "voiced_ratio": 0.8,
                        "audio_quality": {"reliable": True}}}


class _Db:
    def __init__(self, *, assignment=None, request=None, events=(),
                 practices=(), fail=False):
        self.assignment = assignment
        self.request = request
        self.fail = fail
        self.raised: list = []
        self.answer_kinds: list = []
        self.events = list(events)
        self.practices = list(practices)
        self.recorded: list = []

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
        if self.fail:
            raise RuntimeError("down")
        self.raised.append(kwargs)
        self.request = {"id": "req-1", "answer_kind": None, **kwargs}
        return self.request

    def set_exercise_coach_request_answer_kind(self, **kwargs):
        self.answer_kinds.append(kwargs)
        if self.request is None:
            return None
        if kwargs.get("only_if_unset") and self.request.get("answer_kind"):
            return None
        self.request["answer_kind"] = kwargs["answer_kind"]
        return self.request

    def get_snippet_by_id(self, sid):
        return {"id": sid, "session_id": "take-1"} if sid == "snip-1" else None

    def v2_get_session_by_id(self, sid):
        return ({"id": "take-1", "user_id": "owner-1", "arc_id": "arc-1"}
                if sid == "take-1" else None)

    def record_moment_event(self, **kwargs):
        key = (kwargs["take_session_id"], kwargs["snippet_id"], kwargs["event"])
        if key in self.recorded:
            return False
        self.recorded.append(key)
        self.events.append({"snippet_id": kwargs["snippet_id"],
                            "event": kwargs["event"], "created_at": "t1"})
        return True

    def list_moment_events_for_take(self, _take):
        return list(self.events)

    def list_confident_voice_practice_for_take(self, _take, _owner=None):
        return list(self.practices)


def _verdict(read, fired):
    pattern = {"confident": "confident", "weak": "low_confidence_rushing_dominant",
               "unknown": None}[read]
    if pattern is None:
        return {"eligible": False, "reason": "confidence_unavailable"}
    return {"eligible": True, "pattern": pattern, "priority": 1,
            "signals": {"insufficient_pauses": True} if fired else {},
            "snapshot": {}}


def _with_read(read, fired, fn):
    with patch.object(cvp, "exercise_eligibility",
                      lambda *_a, **_k: _verdict(read, fired)):
        return fn()


def _open(db, read="weak", fired=True):
    return _with_read(read, fired, lambda: jf.follow_up_for_open(
        db, take_session_id="take-1", snippet_id="snip-1",
        owner_user_id="owner-1"))


def _answer(db, answer, read="weak", fired=True):
    return _with_read(read, fired, lambda: jf.follow_up_for_judgement(
        db, take_session_id="take-1", snippet_id="snip-1",
        owner_user_id="owner-1", answer=answer))


class OnTests(unittest.TestCase):


    def test_the_judgement_after_the_praise_sets_the_answer_kind(self):
        db = _Db()
        _open(db, "confident", False)
        self.assertEqual(_answer(db, "no", "confident", False), "praise")
        self.assertEqual(db.request["kind"], "praise")
        self.assertEqual(db.request["answer_kind"], "ambiguity")
        self.assertEqual(len(db.raised), 1)
        db = _Db()
        _open(db, "confident", False)
        _answer(db, "in_between", "confident", False)
        self.assertEqual(db.request["answer_kind"], "praise")
