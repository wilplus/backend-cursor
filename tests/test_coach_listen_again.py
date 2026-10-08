"""A coach is asked to listen again, blind (QG12a A, P26b A, P26c; D-CP-10;
migration 0444): the words, the flag, the queue row, the masked state and
the doors it shuts. The database half is
tests/test_a_coach_is_asked_to_listen_again_postgres.py."""
from __future__ import annotations

import inspect
import pathlib
import re
import unittest

from services import coach_listen_again as la
from services.coach_blind_gate import has_committed_blind_label
from services.coach_moments_queue import moments_queue

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALL = lambda _sid: {"s1", "s2"}  # noqa: E731


class WordsTests(unittest.TestCase):
    def test_the_three_keys_name_the_signed_lines_byte_for_byte(self):
        text = (ROOT / "docs" / "SIGNED-line-bank-2026-10-06.md").read_text(encoding="utf-8")
        start = text.index("## The coach's work list (P26c A)")
        end = text.find("\n## ", start + 1)
        section = text[start:end if end > 0 else None]
        signed = re.findall(r"^- (.+)$", section, flags=re.M)
        self.assertEqual(signed, list(la.LINES.values()))
        self.assertEqual(la.LINE_KEYS, ("P26c-A", "P26c-B", "P26c-C"))
        # On purpose the lines say neither why nor what the speaker answered.
        for line in signed:
            for word in ("disagree", "speaker", "machine", "yes", "no", "confident"):
                self.assertNotIn(word, line.lower().split())


class _Db:
    def __init__(self, *, written=1, asks=(), error=None):
        self.written = written
        self.asks = list(asks)
        self.error = error
        self.flags: list = []
        self.heard: list = []

    def request_coach_listen_again(self, take, snippet):
        if self.error:
            raise self.error
        self.flags.append((take, snippet))
        return self.written

    def mark_coach_listen_again_heard(self, snippet, coach):
        self.heard.append((snippet, coach))
        return 1

    def list_open_coach_listen_again(self, coach, session_ids):
        return [a for a in self.asks if a["take_session_id"] in session_ids]


class FlagTests(unittest.TestCase):
    def test_the_flag_is_a_side_write_that_never_raises(self):
        db = _Db(written=2)
        self.assertEqual(la.flag_disagreement(db, take_session_id="t", snippet_id="s"), 2)
        self.assertEqual(db.flags, [("t", "s")])
        self.assertEqual(la.flag_disagreement(_Db(error=RuntimeError("down")),
                                              take_session_id="t", snippet_id="s"), 0)
        self.assertEqual(la.flag_disagreement(object(), take_session_id="t", snippet_id="s"), 0)
        self.assertEqual(la.flag_disagreement(db, take_session_id="", snippet_id="s"), 0)
        self.assertEqual(la.mark_heard(db, snippet_id="s", coach_id="c"), 1)
        self.assertEqual(db.heard, [("s", "c")])
        self.assertEqual(la.mark_heard(object(), snippet_id="s", coach_id="c"), 0)

    def test_the_matrix_flags_exactly_its_ambiguity_cells(self):
        """QG12a A: the speaker's answer disagrees with the machine's read.
        The flag rides every path that writes the ambiguity, and no other."""
        from services import judgement_follow_up as jfu
        source = inspect.getsource(jfu)
        self.assertEqual(source.count("_flag_disagreement(database, "), 3)
        for fn in (jfu.follow_up_for_judgement, jfu._answer_after_feedback, jfu.practice_judgement):
            self.assertIn("_flag_disagreement(", inspect.getsource(fn), fn.__name__)
        self.assertIn('if kind == "ambiguity":', inspect.getsource(jfu.follow_up_for_judgement))
        self.assertIn('if answer_kind == "ambiguity":', inspect.getsource(jfu._answer_after_feedback))
        body = inspect.getsource(jfu.practice_judgement)
        self.assertLess(body.index("if practice_disagrees("), body.index("_flag_disagreement("))
        # Follow-ups that agree with the machine never flag.
        self.assertNotIn("_flag_disagreement", inspect.getsource(jfu.follow_up_for_open))

    def test_a_judgement_that_disagrees_flags_and_one_that_agrees_does_not(self):
        from services import judgement_follow_up as jfu
        from tests.test_judgement_follow_up import _Db as _JfuDb, _verdict

        class Db(_JfuDb):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.flags: list = []

            def request_coach_listen_again(self, take, snippet):
                self.flags.append((take, snippet))
                return 1

        from unittest.mock import patch
        for answer, read, flagged in (("no", "confident", True), ("not_sure", "confident", True),
                                      ("yes", "confident", False), ("yes", "weak", True),
                                      ("no", "weak", False), ("audio_unclear", "confident", False)):
            db = Db()
            with patch("services.confident_voice_practice.exercise_eligibility",
                       return_value=_verdict(read, False)), \
                 patch("services.confident_voice_practice.machine_read", return_value=read), \
                 patch("services.confident_voice_practice.observed_problem_tags", return_value=[]), \
                 patch("services.confident_voice_practice.detected_problem_vocabulary",
                       return_value=frozenset()), \
                 patch.object(jfu, "_raise_request", return_value=True):
                jfu.follow_up_for_judgement(db, take_session_id="take-1", snippet_id="snip-1",
                                            owner_user_id="owner-1", answer=answer)
            self.assertEqual(db.flags, [("take-1", "snip-1")] if flagged else [], (answer, read))


class QueueTests(unittest.TestCase):
    def test_a_moment_with_an_open_ask_rides_blind_with_only_the_line_key(self):
        rows = [{"id": "t1", "user_id": "u", "review_requested_at": "2026-10-07T10:00", "take_index": 1}]
        ratings = {"t1": {"s1": {"value": "no", "unrateable": False},
                          "s2": {"value": "yes", "unrateable": False}}}
        # The request carries the speaker's side (answer_kind 'ambiguity'):
        # a row with an open ask must not carry it.
        requests = {("t1", "s1"): {"kind": "praise", "answer_kind": "ambiguity",
                                   "resolution": "line_written"},
                    ("t1", "s2"): {"kind": "praise", "resolution": None}}
        out = moments_queue(
            rows, moments_for=lambda r: ["s1", "s2"], reached_for=ALL,
            ratings_for=lambda sid: ratings.get(sid, {}),
            request_for=lambda sid, snip: requests.get((sid, snip)),
            pseudonym_for=lambda uid: "Quiet", rater_id="coach-1",
            listen_again_for=lambda sid: {"s1": "P26c-B"} if sid == "t1" else {})
        take = out[0]["takes"][0]
        self.assertEqual(take["moments"], [
            {"snippet_id": "s1", "state": "listen_again", "line_key": "P26c-B"},
            {"snippet_id": "s2", "state": "answer_it", "kind": "praise"},
        ])
        self.assertEqual(take["waiting"], 2)
        self.assertEqual(out[0]["waiting"], 2)
        leaked = {k for k in take["moments"][0]} - {"snippet_id", "state", "line_key"}
        self.assertEqual(leaked, set())
        self.assertNotIn("ambiguity", str(take["moments"][0]))

    def test_without_an_ask_the_queue_is_as_before(self):
        rows = [{"id": "t1", "user_id": "u", "review_requested_at": "x", "take_index": 1}]
        ratings = {"t1": {"s1": {"value": "no", "unrateable": False}}}
        out = moments_queue(
            rows, moments_for=lambda r: ["s1"], reached_for=ALL,
            ratings_for=lambda sid: ratings.get(sid, {}),
            request_for=lambda sid, snip: {"kind": "error", "answer_kind": "ambiguity",
                                           "resolution": None},
            pseudonym_for=lambda uid: "Quiet")
        self.assertEqual(out[0]["takes"][0]["moments"],
                         [{"snippet_id": "s1", "state": "answer_it", "kind": "ambiguity"}])

    def test_open_asks_are_read_per_coach_and_a_failed_read_is_empty(self):
        db = _Db(asks=[{"take_session_id": "t1", "snippet_id": "s1", "line_key": "P26c-C"},
                       {"take_session_id": "t2", "snippet_id": "s9", "line_key": "P26c-A"},
                       {"take_session_id": "t1", "snippet_id": "s3", "line_key": "because"}])
        self.assertEqual(la.open_asks(db, coach_id="c", session_ids=["t1"]),
                         {"t1": {"s1": "P26c-C"}})
        self.assertEqual(la.open_asks(db, coach_id="c", session_ids=[]), {})
        self.assertEqual(la.open_asks(object(), coach_id="c", session_ids=["t1"]), {})

        class Broken:
            def list_open_coach_listen_again(self, *_a):
                raise RuntimeError("down")
        self.assertEqual(la.open_asks(Broken(), coach_id="c", session_ids=["t1"]), {})


class DoorsTests(unittest.TestCase):
    def test_the_masked_state_shuts_every_door_keyed_on_the_rating(self):
        from routes.v2.coach import _practice_door_open
        rated = {"note": "", "tag": None, "surfaced": False, "transcript_corrected": None,
                 "rating_value": "no", "rating_unrateable": False}
        self.assertTrue(_practice_door_open(rated))
        self.assertTrue(has_committed_blind_label(rated))
        masked = la.masked_state(rated, "P26c-A")
        self.assertFalse(_practice_door_open(masked))
        self.assertFalse(has_committed_blind_label(masked))
        self.assertEqual(masked["listen_again"], "P26c-A")
        self.assertIsNone(masked["rating_value"])
        # The earlier answer is not in the masked state at all.
        self.assertNotIn("no", [v for v in masked.values() if isinstance(v, str)])
        states = la.mask_states({"s1": rated, "s2": dict(rated)}, {"s1": "P26c-B", "s3": "P26c-C"})
        self.assertFalse(has_committed_blind_label(states["s1"]))
        self.assertTrue(has_committed_blind_label(states["s2"]))
        self.assertEqual(states["s3"]["listen_again"], "P26c-C")
        untouched = {"s1": rated}
        self.assertIs(la.mask_states(untouched, {}), untouched)

    def test_the_state_map_masks_and_the_gate_and_the_session_read_key_on_it(self):
        """Nothing leaks before the coach rates again: the one map every
        blind door reads is masked while an ask is open (BLIND COACH)."""
        from routes.v2 import coach
        state_map = inspect.getsource(coach._coach_state_map)
        self.assertIn("open_asks(db, coach_id=rater_id, session_ids=[session_id])", state_map)
        self.assertIn("mask_states(out,", state_map)
        gate = inspect.getsource(coach._moment_gate)
        self.assertIn("_coach_state_map(owner_sid, rater_id=", gate)
        self.assertIn("_practice_door_open(", gate)
        self.assertIn("BLIND_RATING_REQUIRED", gate)
        session_read = inspect.getsource(coach.v2_coach_get_session)
        self.assertIn("_coach_state_map(\n            session_id, rater_id=", session_read)
        self.assertIn("redact_contextual_snippets(snippets)", session_read)
        shaped = inspect.getsource(coach._shape_coach_review_snippet)
        self.assertIn("committed=has_committed_blind_label(_coach_state)", shaped)
        # The new blind answer closes the ask: the reconsideration path only.
        self.assertIn("mark_heard(db, snippet_id=snippet_id, coach_id=rater_id)",
                      inspect.getsource(coach._reconsider_coach_rating))
        self.assertNotIn("mark_heard", inspect.getsource(coach._first_coach_rating))

    def test_the_queue_reads_this_coach_s_asks(self):
        from services import coach_moments_queue as q
        source = inspect.getsource(q.queue_for_coach)
        self.assertIn("open_asks(database, coach_id=rater_id, session_ids=ids)", source)
        self.assertIn("listen_again_for=", source)
        self.assertIn("listen_again", q.STATES)

    def test_both_go_with_the_take_and_with_the_coach(self):
        from services.data_purge_registry import DEPENDENCIES
        keyed = {(d.selector_column, d.locator_kind, d.disposition)
                 for d in DEPENDENCIES if d.relation == "coach_listen_again_requests"}
        self.assertEqual(keyed, {("take_session_id", "take", "delete"),
                                 ("coach_id", "user", "delete")})

    def test_the_migration_holds_the_standing_rules(self):
        sql = (ROOT / "migrations" / "a_coach_is_asked_to_listen_again.sql").read_text()
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("REVOKE ALL ON TABLE public.coach_listen_again_requests FROM PUBLIC", sql)
        for fn in ("request_coach_listen_again_v1(text, text)",
                   "mark_coach_listen_again_heard_v1(text, text)"):
            self.assertIn(f"REVOKE ALL ON FUNCTION public.{fn} FROM PUBLIC", sql)
            self.assertIn(f"GRANT EXECUTE ON FUNCTION public.{fn} TO service_role", sql)
        self.assertEqual(sql.count("SECURITY DEFINER SET search_path = public"), 2)
        for word in ("reason", "answer_value", "machine_read", "speaker_answer"):
            self.assertNotRegex(sql, rf"^\s+{word}\s+\w+", word)
        self.assertIn("Rollback (a new forward migration)", sql)

    def test_the_rotation_reads_the_latest_line_under_a_coach_lock(self):
        """Review fixes: the line after the coach's latest (a purge cannot
        make a line repeat), one rotation per coach at a time, the one-open
        index decides duplicates (no check-then-insert race), the moment in
        canonical uuid text, and only blind judgments of record."""
        sql = (ROOT / "migrations" / "a_coach_is_asked_to_listen_again.sql").read_text()
        body = sql[sql.index("FUNCTION public.request_coach_listen_again_v1("):
                   sql.index("FUNCTION public.mark_coach_listen_again_heard_v1(")]
        self.assertIn("pg_advisory_xact_lock(hashtext('coach_listen_again:' || v_coach))", body)
        self.assertIn("ORDER BY requested_at DESC, id DESC", body)
        self.assertNotIn("count(*)", body)
        self.assertNotIn("IF EXISTS", body)
        self.assertIn("ON CONFLICT (snippet_id, coach_id) WHERE heard_at IS NULL DO NOTHING", body)
        self.assertIn("v_key := v_snippet::text;", body)
        self.assertIn("AND label.blind IS NOT FALSE", body)
        self.assertLess(body.index("pg_advisory_xact_lock"), body.index("SELECT line_key"))
        mark = sql[sql.index("FUNCTION public.mark_coach_listen_again_heard_v1("):]
        self.assertIn("v_key := p_snippet_id::uuid::text;", mark)
