"""
STORY    As a speaker, I want to judge myself after the feedback and not
         before, with my answer shown to the coach only after their blind
         rating, so that the machine leads and the coach stays blind.
OUTCOME
  O1  Opening a moment raises one coach request, under the machine's kind,
      once; it never asks me for a judgement first.
  O2  My later answer sets the request's answer_kind from the matrix.
  O3  Never-2 (coach judgements stay blind): when my practice judgement
      disagrees with the machine's read, the moment becomes an ambiguity and
      coaches who already judged it are asked to listen again, blind; an
      agreeing judgement confirms the kind once.
  O4  A clip with no read, and an Audio unclear answer, send nothing.
  O5  A skipped bookmark, a landed or a dismissed practice settle the
      moment without an answer.
PROVES   O1 -> test_the_open_raises_one_request_of_the_machines_kind
         O2 -> test_the_judgement_after_the_praise_sets_the_answer_kind
         O3 -> test_a_practice_judgement_that_disagrees_is_an_ambiguity
         O4 -> test_no_read_and_audio_unclear_send_nothing
         O5 -> test_skips_and_closed_practices_settle_without_an_answer
WHY      Founder 2026-10-01, F1: "Opening a bookmark never asks for a
         judgment first." (The coach's blind gate on the speaker's side is
         proven in tests/test_the_machine_heard.py.)
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import confident_voice_practice as cvp
from services import judgement_follow_up as jf
from services import moment_events as me


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
        self.listen_again: list = []

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

    def request_coach_listen_again(self, take, snip):
        self.listen_again.append((take, snip))
        return 1


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

    def test_the_open_raises_one_request_of_the_machines_kind(self):
        db = _Db()
        self.assertEqual(_open(db, "weak", True), "coach_request")
        self.assertEqual(len(db.raised), 1)
        self.assertEqual(db.raised[0]["kind"], "error")
        self.assertEqual(db.raised[0]["raised_on"], "open")
        self.assertEqual(db.answer_kinds, [])  # no judgement asked for
        _open(db, "weak", True)
        self.assertEqual(len(db.raised), 1)  # insert-once

    def test_a_practice_judgement_that_disagrees_is_an_ambiguity(self):
        practice = {"take_session_id": "take-1", "snippet_id": "snip-1"}
        db = _Db(request={"id": "req-1", "kind": "error", "answer_kind": None})
        self.assertEqual(jf.practice_judgement(db, practice, "yes", "no"),
                         "ambiguity")
        self.assertEqual(db.request["answer_kind"], "ambiguity")
        self.assertEqual(db.listen_again, [("take-1", "snip-1")])
        db = _Db(request={"id": "req-1", "kind": "error", "answer_kind": None})
        self.assertEqual(jf.practice_judgement(db, practice, "no", "no"),
                         "error")
        self.assertIsNone(jf.practice_judgement(db, practice, "no", "no"))
        self.assertEqual(db.listen_again, [])

    def test_no_read_and_audio_unclear_send_nothing(self):
        db = _Db()
        self.assertEqual(_answer(db, "audio_unclear"), "none")
        _open(db, "unknown", False)
        _answer(db, "no", "unknown", False)
        db.get_confident_voice_practice_candidates = lambda _ids: []
        self.assertEqual(_answer(db, "no"), "none")
        self.assertEqual((db.raised, db.answer_kinds), ([], []))
        # ...while a readable clip does reach the coach.
        readable = _Db()
        _answer(readable, "no")
        self.assertEqual(len(readable.raised), 1)

    def test_skips_and_closed_practices_settle_without_an_answer(self):
        db = _Db(practices=[
            {"snippet_id": "snip-2", "status": "completed",
             "final_user_answer": "yes"},
            {"snippet_id": "snip-3", "status": "dismissed"}])
        with patch("services.ideal_text_feedback_bake."
                   "request_rebake_after_answer"):
            status, body = me.record_moment_event(
                db, user_id="owner-1", snippet_id="snip-1",
                body={"event": "skipped"})
        self.assertEqual((status, body["recorded"]), (200, True))
        self.assertEqual(
            me.settled_status_by_moment(db, take_session_id="take-1",
                                        owner_user_id="owner-1"),
            {"snip-1": "dismissed", "snip-2": "approved",
             "snip-3": "dismissed"})
        self.assertEqual((db.raised, db.answer_kinds), ([], []))


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
