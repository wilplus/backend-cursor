"""The speaker's own history in exercise ranking (step 7, founder 2026-09-28).

Pins:
  * a problem is REPEATED once spotted on 2+ earlier Takes (distinct Takes,
    not repeated rows); a failed or absent read ranks exactly as before;
  * among equally good fits, the exercise for the speaker's repeated problem
    comes first, and one they already did comes after one they haven't —
    never removed, so a speaker with only done-before exercises still gets one;
  * fit and coverage still come first: history only breaks ties (D5/D6 hold);
  * history is read only when the moment is drawn for the first time, and
    frozen into the trace;
  * the practice-start re-rank uses the same history as the offer.
"""
from __future__ import annotations

import unittest

from services import confident_voice_practice as cvp
from tests.test_confident_voice_practice import V3ExerciseFitTests, _snippet


def _exercise(exercise_id, tags, primary=None):
    return V3ExerciseFitTests._row(None, exercise_id, tags, primary)


def _history(repeated=(), done=()):
    return {"repeated_patterns": frozenset(repeated),
            "done_before": frozenset(done), "earlier_takes": 3,
            "available": True}


def _rank(exercises, fired, history=None):
    _, matched = cvp.matched_exercises(
        "near_confident", exercises, observed_tags=frozenset(fired),
        history=history)
    return [item[1]["exercise_id"] for item in matched]


class _HistoryDb:
    def __init__(self, raw=None, fail=False):
        self.raw = raw
        self.fail = fail
        self.calls = 0

    def speaker_exercise_history(self, owner, take, *, limit):
        self.calls += 1
        if self.fail:
            raise RuntimeError("relation does not exist")
        return self.raw


class SpeakerHistoryTests(unittest.TestCase):
    def test_repeated_means_two_distinct_earlier_takes(self):
        history = cvp.speaker_history(_HistoryDb({
            "pattern_takes": {"rushing": ["t1", "t2"],
                              "ending_compression": ["t1"],
                              "word_compression": ["t3", "t3"]},
            "completed_exercises": ["room-to-follow"], "earlier_takes": 3,
        }), "owner-1", "take-9")
        self.assertEqual(history["repeated_patterns"], frozenset({"rushing"}))
        self.assertEqual(history["done_before"], frozenset({"room-to-follow"}))
        self.assertTrue(history["available"])

    def test_no_owner_or_a_failed_read_is_no_history(self):
        for db, owner in ((_HistoryDb(fail=True), "owner-1"),
                          (_HistoryDb({}), ""), (object(), "owner-1")):
            history = cvp.speaker_history(db, owner, "take-9")
            self.assertEqual(history["repeated_patterns"], frozenset())
            self.assertFalse(history["available"])


class RankingTests(unittest.TestCase):
    def test_the_speaker_s_repeated_problem_breaks_a_tie(self):
        a = _exercise("a-ending", ["ending_compression"])
        b = _exercise("b-rushing", ["rushing"])
        fired = {"ending_compression", "rushing"}
        self.assertEqual(_rank([a, b], fired), ["a-ending", "b-rushing"])
        self.assertEqual(_rank([a, b], fired, _history(repeated={"rushing"})),
                         ["b-rushing", "a-ending"])

    def test_done_before_ranks_after_but_is_never_removed(self):
        a = _exercise("a", ["rushing"])
        b = _exercise("b", ["rushing"])
        self.assertEqual(_rank([a, b], {"rushing"}, _history(done={"a"})),
                         ["b", "a"])
        self.assertEqual(_rank([a], {"rushing"}, _history(done={"a"})), ["a"])

    def test_history_never_outranks_fit_or_coverage(self):
        exact = _exercise("exact", ["rushing"], primary="rushing")
        trial = _exercise("trial", ["word_compression", "rushing"],
                          primary="word_compression")
        # The trial is not even in the pool while an exact fit exists (D6),
        # whatever the history says.
        self.assertEqual(
            _rank([trial, exact], {"rushing"},
                  _history(repeated={"rushing"}, done={"exact"})), ["exact"])
        both = _exercise("both", ["rushing", "ending_compression"])
        one = _exercise("one", ["ending_compression"])
        self.assertEqual(
            _rank([one, both], {"rushing", "ending_compression"},
                  _history(repeated={"ending_compression"}, done={"both"})),
            ["both", "one"])

    def test_without_history_nothing_changes(self):
        a = _exercise("a", ["rushing"])
        b = _exercise("b", ["rushing", "ending_compression"])
        self.assertEqual(_rank([a, b], {"rushing"}),
                         _rank([a, b], {"rushing"}, cvp.EMPTY_HISTORY))


class _LaneDb(V3ExerciseFitTests._Db):
    def __init__(self, rows, *, drawn=None, raw=None):
        super().__init__(rows, {})
        self.drawn = drawn
        self.raw = raw
        self.history_reads = 0

    def get_confident_voice_exercise_assignment(self, _take, _snippet):
        return self.drawn

    def speaker_exercise_history(self, owner, take, *, limit):
        self.history_reads += 1
        return self.raw or {}


class LaneTests(unittest.TestCase):
    ROWS = [_exercise("a-ending", ["ending_compression"]),
            _exercise("b-rushing", ["rushing"])]
    FIRED = {"insufficient_pauses": True, "compressed_ending": True}
    RAW = {"pattern_takes": {"rushing": ["t1", "t2"]},
           "completed_exercises": ["a-ending"], "earlier_takes": 2}

    def test_a_first_draw_ranks_with_history_and_freezes_it(self):
        db = _LaneDb(self.ROWS, raw=self.RAW)
        V3ExerciseFitTests._offer(None, db, self.FIRED)
        self.assertEqual(db.history_reads, 1)
        call = db.assigned[0]
        self.assertEqual([c["exercise_id"] for c in call["candidates"]],
                         ["b-rushing", "a-ending"])
        history = call["trace"]["history"]
        self.assertEqual(history["repeated_patterns"], ["rushing"])
        self.assertEqual(history["done_before"], ["a-ending"])
        by_id = {c["exercise_id"]: c for c in call["trace"]["candidates"]}
        self.assertEqual(by_id["b-rushing"]["repeat_hits"], 1)
        self.assertTrue(by_id["a-ending"]["done_before"])

    def test_an_already_drawn_moment_reads_no_history(self):
        db = _LaneDb(self.ROWS, drawn={"id": "asg", "selected_exercise_id":
                                       "a-ending"}, raw=self.RAW)
        V3ExerciseFitTests._offer(None, db, self.FIRED)
        self.assertEqual(db.history_reads, 0)

    def test_the_start_check_ranks_with_the_same_history(self):
        db = _LaneDb(self.ROWS, raw=self.RAW)
        original = cvp.exercise_eligibility
        cvp.exercise_eligibility = lambda *_a, **_k: {
            "eligible": True, "pattern": "near_confident",
            "signals": self.FIRED, "snapshot": {}}
        try:
            refusal, _, _ = cvp.start_exercise_check(
                snippet=_snippet(id="snippet-a"), take_session_id="take-1",
                snippet_id="snippet-a", exercise_id="b-rushing",
                session_median_wpm=150, database=db, owner_user_id="owner-1")
            self.assertIsNone(refusal)
            refusal, _, _ = cvp.start_exercise_check(
                snippet=_snippet(id="snippet-a"), take_session_id="take-1",
                snippet_id="snippet-a", exercise_id="a-ending",
                session_median_wpm=150, database=db, owner_user_id="owner-1")
            self.assertEqual(refusal, "EXERCISE_OFFER_STALE")
        finally:
            cvp.exercise_eligibility = original


class _Query:
    def __init__(self, rows, log, table):
        self.rows, self.log, self.table = rows, log, table

    def __getattr__(self, name):
        def step(*args, **kwargs):
            self.log.append((self.table, name, args))
            return self
        return step

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Client:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def table(self, name):
        return _Query(self.tables.get(name, []), self.log, name)


class DatabaseReadTests(unittest.TestCase):
    def test_problems_are_counted_per_distinct_earlier_take(self):
        from services.db import DatabaseService
        db = object.__new__(DatabaseService)
        db.client = _Client({
            "confident_voice_exercise_assignments": [
                {"id": "a1", "take_session_id": "t1"},
                {"id": "a2", "take_session_id": "t2"}],
            "confident_voice_exercise_match_traces": [
                {"assignment_id": "a1", "observed_tags": ["rushing"]},
                {"assignment_id": "a2", "observed_tags": ["rushing",
                                                          "rushing"]}],
            "exercise_coach_requests": [
                {"take_session_id": "t3", "observed_tags": ["ending_compression"]},
                {"take_session_id": "t1", "observed_tags": ["rushing"]}],
            "confident_voice_practice": [
                {"exercise_id": "room-to-follow"}, {"exercise_id": None}],
        })
        raw = db.speaker_exercise_history("owner-1", "t9", limit=20)
        self.assertEqual(raw["pattern_takes"], {
            "rushing": ["t1", "t2"], "ending_compression": ["t3"]})
        self.assertEqual(raw["completed_exercises"], ["room-to-follow"])
        self.assertEqual(raw["earlier_takes"], 3)
        # The current Take is excluded everywhere it is read.
        excluded = [entry for entry in db.client.log
                    if entry[1] == "neq" and entry[2] == ("take_session_id", "t9")]
        self.assertEqual(len(excluded), 3)
        history = cvp.speaker_history(db, "owner-1", "t9")
        self.assertEqual(history["repeated_patterns"], frozenset({"rushing"}))
