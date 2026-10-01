"""Judgement after feedback (founder 2026-10-01, F1; Phase 2 of the
after-practice paths), dark behind JUDGEMENT_AFTER_FEEDBACK_ENABLED.

F1: "Opening a bookmark never asks for a judgment first. The machine's read
chooses the feedback. The speaker judges themselves after it: on a confident
moment right after the praise, on a moment that needed work after each
practice attempt. Helper words open on Yes or In-between of that judgment."

Pins: off, the open is a receipt and the judgement flow is exactly today's;
on, the open raises the moment's request under the machine's kind
(insert-once, raised at the open), the later judgement sets its answer_kind
from the matrix, a practice judgement that disagrees with the machine's
read of the attempt makes it an ambiguity, no read and Audio unclear send
nothing, the practice may start without an answer, a landed or dismissed
practice or a skipped bookmark settles the item without a Path 1 answer,
and the coach reads the speaker's side only after the blind rating.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from services import confident_voice_practice as cvp
from services import judgement_follow_up as jf
from services.coach_load import coach_load
from services.coach_moments_queue import moment_state
from services.exercise_coach_requests import _moment_event_fields
from services.moment_events import (
    co_exposed_from, record_moment_event, settled_status_by_moment,
)

ROOT = Path(__file__).resolve().parents[1]
ON = patch("config.Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED", True)


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


def _event(db, event, shown=("praise",), read="weak", fired=True):
    return _with_read(read, fired, lambda: record_moment_event(
        db, user_id="owner-1", snippet_id="snip-1",
        body={"event": event, "shown": list(shown)}))


PRACTICE = {"id": "p-1", "take_session_id": "take-1", "snippet_id": "snip-1"}


class OffTests(unittest.TestCase):
    def test_the_switch_is_off(self):
        from config import Config as _live
        self.assertFalse(_live.JUDGEMENT_AFTER_FEEDBACK_ENABLED)

    def test_off_the_open_is_a_receipt_and_raises_nothing(self):
        db = _Db()
        self.assertEqual(_event(db, "opened"),
                         (200, {"recorded": True, "follow_up": "none"}))
        self.assertEqual(_event(db, "opened")[1]["recorded"], False)
        self.assertEqual(_event(db, "skipped")[1]["recorded"], True)
        self.assertEqual(db.raised, [])

    def test_off_the_judgement_flow_is_exactly_todays(self):
        db = _Db()
        self.assertEqual(_answer(db, "no"), "coach_request")
        self.assertEqual(db.raised[0]["kind"], "error")
        self.assertNotIn("raised_on", db.raised[0])
        self.assertEqual(db.answer_kinds, [])
        self.assertIsNone(jf.practice_judgement(db, PRACTICE, "yes", "no"))

    def test_off_the_settled_read_and_the_start_gate_never_run(self):
        source = (ROOT / "services/ideal_text_changes.py").read_text()
        start = source.index("def _mark_settled_without_answer")
        body = source[start:source.index("def _decision_backfill")]
        self.assertIn("if not judgement_after_feedback_enabled()", body)
        routes = (ROOT / "routes/v2/user_sessions.py").read_text()
        for name in ("_practice_original_answer", "_practice_answer_gate"):
            start = routes.index(f"def {name}")
            self.assertIn("judgement_after_feedback_enabled()",
                          routes[start:start + 900], name)


class OpenMatrixTests(unittest.TestCase):
    def test_the_read_chooses_the_feedback_and_the_kind(self):
        self.assertEqual(jf.decide_at_open("confident", True, True), ("praise", "praise"))
        self.assertEqual(jf.decide_at_open("confident", False, False), ("praise", "praise"))
        self.assertEqual(jf.decide_at_open("weak", True, True), ("exercise", "error"))
        self.assertEqual(jf.decide_at_open("weak", True, False), ("coach_request", "error"))
        self.assertEqual(jf.decide_at_open("weak", False, False), ("rewrite", "rewrite"))
        self.assertEqual(jf.decide_at_open("unknown", False, False), ("rewrite", None))

    def test_the_answer_kind_is_the_matrix_s_kind(self):
        self.assertEqual(jf.answer_kind_for("yes", "confident", False), "praise")
        self.assertEqual(jf.answer_kind_for("no", "confident", False), "ambiguity")
        self.assertEqual(jf.answer_kind_for("yes", "weak", True), "ambiguity")
        self.assertEqual(jf.answer_kind_for("no", "weak", True), "error")
        self.assertEqual(jf.answer_kind_for("in_between", "weak", False), "rewrite")
        self.assertEqual(jf.answer_kind_for("not_sure", "weak", False), "ambiguity")
        self.assertIsNone(jf.answer_kind_for("audio_unclear", "weak", True))

    def test_the_practice_disagreement_rule(self):
        self.assertTrue(jf.practice_disagrees("yes", "no"))
        self.assertTrue(jf.practice_disagrees("in_between", "no"))
        self.assertTrue(jf.practice_disagrees("no", "yes"))
        self.assertTrue(jf.practice_disagrees("not_sure", "yes"))
        self.assertFalse(jf.practice_disagrees("yes", "yes"))
        self.assertFalse(jf.practice_disagrees("no", "no"))
        self.assertFalse(jf.practice_disagrees("yes", None))
        self.assertFalse(jf.practice_disagrees("audio_unclear", "yes"))


@ON
class OnTests(unittest.TestCase):
    def test_the_open_raises_the_request_under_the_machine_s_kind(self):
        db = _Db()
        self.assertEqual(_open(db, "weak", True), "coach_request")
        call = db.raised[0]
        self.assertEqual((call["kind"], call["raised_on"], call["reason"]),
                         ("error", "open", "nothing_targets_it"))
        self.assertEqual(call["observed_tags"], ["rushing"])
        self.assertEqual(call["request_trace"]["lane"], jf.JUDGEMENT_LANE)

    def test_a_matched_moment_opens_on_the_exercise(self):
        db = _Db(assignment={"selected_exercise_id": "x"})
        self.assertEqual(_open(db, "weak", True), "exercise")
        self.assertEqual(db.raised[0]["reason"], "library_matched")

    def test_a_confident_moment_opens_on_the_praise(self):
        db = _Db()
        self.assertEqual(_open(db, "confident", False), "praise")
        self.assertEqual(db.raised[0]["kind"], "praise")

    def test_nothing_fired_opens_on_the_rewrite(self):
        db = _Db()
        self.assertEqual(_open(db, "weak", False), "rewrite")
        self.assertEqual(db.raised[0]["kind"], "rewrite")

    def test_no_read_opens_on_the_rewrite_and_raises_nothing(self):
        db = _Db()
        self.assertEqual(_open(db, "unknown", False), "rewrite")
        self.assertEqual(db.raised, [])

    def test_the_open_is_insert_once(self):
        db = _Db()
        _open(db)
        _open(db)
        self.assertEqual(len(db.raised), 1)

    def test_a_request_that_cannot_be_written_promises_nothing(self):
        db = _Db(fail=True)
        self.assertEqual(_open(db, "weak", True), "none")
        self.assertEqual(_open(db, "confident", False), "praise")

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

    def test_an_unreported_open_raises_at_the_answer_under_the_machine_s_kind(self):
        db = _Db()
        self.assertEqual(_answer(db, "not_sure", "weak", True), "coach_request")
        self.assertEqual((db.raised[0]["kind"], db.raised[0]["raised_on"]),
                         ("error", "open"))
        self.assertEqual(db.request["answer_kind"], "ambiguity")

    def test_audio_unclear_and_no_read_send_nothing(self):
        db = _Db()
        self.assertEqual(_answer(db, "audio_unclear"), "none")
        self.assertEqual(_answer(db, "no", "unknown", False), "none")
        self.assertEqual(db.raised, [])
        self.assertEqual(db.answer_kinds, [])

    def test_a_practice_judgement_disagreeing_with_the_read_is_an_ambiguity(self):
        db = _Db(request={"id": "r", "kind": "error", "answer_kind": None})
        self.assertEqual(jf.practice_judgement(db, PRACTICE, "yes", "no"), "ambiguity")
        self.assertEqual(db.request["answer_kind"], "ambiguity")
        # Agreement confirms the kind once; a later agreement writes nothing;
        # a later disagreement still makes it an ambiguity.
        db = _Db(request={"id": "r", "kind": "error", "answer_kind": None})
        self.assertEqual(jf.practice_judgement(db, PRACTICE, "no", "no"), "error")
        self.assertIsNone(jf.practice_judgement(db, PRACTICE, "no", "no"))
        self.assertEqual(jf.practice_judgement(db, PRACTICE, "yes", "no"), "ambiguity")
        # A missing machine leg disagrees with nothing; no request, nothing.
        db = _Db(request={"id": "r", "kind": "rewrite", "answer_kind": None})
        self.assertEqual(jf.practice_judgement(db, PRACTICE, "yes", None), "rewrite")
        self.assertIsNone(jf.practice_judgement(_Db(), PRACTICE, "yes", "no"))
        self.assertIsNone(jf.practice_judgement(db, PRACTICE, "audio_unclear", "no"))

    def test_the_judge_attempt_path_asks_the_rule(self):
        source = (ROOT / "services/practice_adoption.py").read_text()
        start = source.index("def judge_attempt")
        body = source[start:source.index("def helper_words_from_practice")]
        self.assertIn("practice_judgement(database, practice, str(answer),", body)
        self.assertIn('target.get("machine_confidence_decision")', body)

    def test_the_open_receipt_says_what_shows_and_a_skip_raises_nothing(self):
        db = _Db()
        self.assertEqual(_event(db, "opened"),
                         (200, {"recorded": True, "follow_up": "coach_request"}))
        self.assertEqual(len(db.raised), 1)
        db = _Db()
        self.assertEqual(_event(db, "skipped"),
                         (200, {"recorded": True, "follow_up": "none"}))
        self.assertEqual(db.raised, [])

    def test_the_receipt_refuses_a_stranger_and_a_bad_event(self):
        db = _Db()
        self.assertEqual(record_moment_event(
            db, user_id="someone-else", snippet_id="snip-1",
            body={"event": "opened"})[0], 404)
        self.assertEqual(record_moment_event(
            db, user_id="owner-1", snippet_id="snip-1",
            body={"event": "peeked"})[0], 400)
        self.assertEqual(db.recorded, [])

    def test_the_practice_may_start_without_an_answer(self):
        from routes.v2.user_sessions import (
            _practice_answer_gate, _practice_original_answer,
        )
        self.assertEqual(_practice_original_answer({}), (None, None))
        self.assertEqual(_practice_original_answer({"original_user_answer": "no"}),
                         ("no", None))
        self.assertIsNone(_practice_answer_gate(
            None, session={"arc_id": "arc-1"}, snippet_id="snip-1",
            user_id="owner-1", answer=None))


class ReceiptTests(unittest.TestCase):
    def test_the_receipt_keeps_only_the_known_kinds(self):
        self.assertEqual(co_exposed_from({"shown": ["praise", "x", 3, "praise"]}),
                         {"shown": ["praise"]})
        self.assertEqual(co_exposed_from({"shown": "praise"}), {"shown": []})
        self.assertEqual(co_exposed_from(None), {"shown": []})


class SettledTests(unittest.TestCase):
    def test_a_landed_practice_approves_a_skip_or_a_dismissal_dismisses(self):
        db = _Db(events=[{"snippet_id": "s1", "event": "skipped"},
                         {"snippet_id": "s5", "event": "opened"}],
                 practices=[{"snippet_id": "s2", "status": "completed",
                             "final_user_answer": "yes"},
                            {"snippet_id": "s3", "status": "dismissed"},
                            {"snippet_id": "s4", "status": "completed",
                             "final_user_answer": "no"},
                            {"snippet_id": "s6", "status": "open"}])
        self.assertEqual(
            settled_status_by_moment(db, take_session_id="take-1", owner_user_id="owner-1"),
            {"s1": "dismissed", "s2": "approved", "s3": "dismissed", "s4": "dismissed"})

    def test_a_practice_outranks_a_skip(self):
        db = _Db(events=[{"snippet_id": "s1", "event": "skipped"}],
                 practices=[{"snippet_id": "s1", "status": "completed",
                             "final_user_answer": "in_between"}])
        self.assertEqual(settled_status_by_moment(
            db, take_session_id="take-1", owner_user_id=None), {"s1": "approved"})

    def test_a_failed_read_keeps_the_bar(self):
        class _Down(_Db):
            def list_moment_events_for_take(self, _take):
                raise RuntimeError("down")
        self.assertEqual(settled_status_by_moment(
            _Down(), take_session_id="take-1", owner_user_id=None), {})


class CoachSideTests(unittest.TestCase):
    def test_the_queue_reads_the_speaker_s_side_once_judged(self):
        self.assertEqual(moment_state({"value": "no"},
                                      {"kind": "error", "answer_kind": "ambiguity"}),
                         {"state": "answer_it", "kind": "ambiguity"})
        self.assertEqual(moment_state({"value": "no"}, {"kind": "error"}),
                         {"state": "answer_it", "kind": "error"})
        # Before the rating nothing rides (BLIND COACH), as before.
        self.assertEqual(moment_state(None, {"kind": "error", "answer_kind": "praise"}),
                         {"state": "judge_it"})

    def test_the_coach_payload_reads_the_answer_kind_and_the_open(self):
        source = (ROOT / "services/exercise_coach_requests.py").read_text()
        self.assertIn('request.get("answer_kind") or request.get("kind")', source)
        db = _Db(events=[{"snippet_id": "snip-1", "event": "opened", "created_at": "t1"},
                         {"snippet_id": "other", "event": "skipped", "created_at": "t2"}])
        self.assertEqual(_moment_event_fields(
            {"take_session_id": "take-1", "snippet_id": "snip-1"}, db),
            {"opened_at": "t1", "skipped_at": None})
        self.assertEqual(_moment_event_fields({"take_session_id": "t", "snippet_id": "s"}, object()),
                         {"opened_at": None, "skipped_at": None})

    def test_the_coach_load_report_splits_by_where_and_kind(self):
        class _Ledger:
            def count_moment_events(self, event, since):
                return 4 if event == "opened" else 0

            def list_exercise_coach_requests(self, since):
                return [{"raised_on": "open", "kind": "error", "answer_kind": None},
                        {"raised_on": "open", "kind": "error", "answer_kind": "ambiguity"},
                        {"raised_on": "judgement", "kind": "praise"},
                        {"kind": "rewrite"}]
        out = coach_load(_Ledger(), since="2026-09-03T00:00:00+00:00")
        self.assertEqual(out["moments_opened"], 4)
        self.assertEqual(out["requests"]["open"], {"error": 1, "praise": 0, "rewrite": 0, "ambiguity": 1})
        self.assertEqual(out["requests"]["judgement"], {"error": 0, "praise": 1, "rewrite": 1, "ambiguity": 0})
        self.assertEqual(out["per_opened_moment"], {"open": 0.5, "judgement": 0.5})
        ledger = (ROOT / "services/learning_ledger.py").read_text()
        self.assertIn('"coach_load": load', ledger)


class ContractTests(unittest.TestCase):
    def test_the_contract_the_config_and_the_migration_record_f1(self):
        contract = (ROOT / "docs/CANONICAL_PRODUCT_CONTRACT.md").read_text()
        self.assertIn("Opening a bookmark never asks for a judgment first", contract)
        self.assertIn("JUDGEMENT_AFTER_FEEDBACK_ENABLED = False",
                      (ROOT / "config.py").read_text())
        sql = (ROOT / "migrations/a_moment_opens_before_it_is_judged.sql").read_text()
        for needle in ("ADD COLUMN IF NOT EXISTS answer_kind",
                       "ADD COLUMN IF NOT EXISTS raised_on",
                       "CREATE TABLE IF NOT EXISTS public.moment_events",
                       "request_exercise_from_coach_v3"):
            self.assertIn(needle, sql)
        self.assertIn("a_moment_opens_before_it_is_judged.sql",
                      (ROOT / "migrations/manifest.txt").read_text())

    def test_the_new_table_is_purged_with_the_take(self):
        from services.data_purge_registry import DEPENDENCIES
        rows = [d for d in DEPENDENCIES if d.relation == "moment_events"]
        self.assertEqual([(d.selector_column, d.locator_kind, d.disposition) for d in rows],
                         [("take_session_id", "take", "delete")])

    def test_the_route_is_a_receipt_that_asks_the_service(self):
        source = (ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index("def v2_moment_event")
        route = source[start:source.index("def _practice_original_answer")]
        self.assertIn("record_moment_event(", route)
        self.assertNotIn("db.", route.replace("record_moment_event(\n            db,", ""))
