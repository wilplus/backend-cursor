"""Change my answer (coach panel lock flows 7 and 12; Q-B12 A; Q-B13 A;
D-CP-7; migration 0446): the app's side. The database half is
tests/test_a_coach_may_change_their_answer_postgres.py."""
from __future__ import annotations

import inspect
import pathlib
import unittest

from services import exercise_coach_requests as ecr
from services.coach_request_drafts import changed_by_another_coach
from services.confident_voice_practice import coach_shared_answer

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self):
        self.lines: list = []
        self.pairs: list = []

    def insert_feedback_catalogue_line(self, **fields):
        self.lines.append(fields)
        return fields

    def insert_feedback_pair(self, **fields):
        self.pairs.append(fields)
        return fields

    def list_speaking_errors(self):
        return []


def _request(**extra):
    return {"id": "req-1", "owner_user_id": "owner-1", "take_session_id": "t",
            "snippet_id": "s", "observed_tags": ["rushing"], "kind": "praise",
            "resolution": None, "answer_text": None, "resolved_by": None, **extra}


class ResolverTests(unittest.TestCase):
    def test_every_answer_goes_through_the_v3_resolver(self):
        from services import db as dbmod
        source = inspect.getsource(dbmod.DatabaseService.resolve_exercise_coach_request)
        self.assertIn('"resolve_exercise_coach_request_v3"', source)
        self.assertNotIn("resolve_exercise_coach_request_v1", source)
        self.assertNotIn("resolve_exercise_coach_request_v2", source)
        self.assertIn('"p_answer_text": None if answer_text is None', source)

    def test_the_refusal_names_another_coach_s_answer(self):
        status, message = ecr._REFUSALS["EXERCISE_COACH_REQUEST_ALREADY_RESOLVED"]
        self.assertEqual(status, 409)
        self.assertIn("another coach", message)


class NoDuplicatePraiseTests(unittest.TestCase):
    def test_the_same_praise_again_files_nothing_and_new_words_file_the_next_version(self):
        previous = _request(resolution="line_written", answer_text="Well said.",
                            resolved_by="coach-1")
        same = dict(previous, answer_text=" Well   said. ")
        self.assertTrue(ecr.answer_unchanged(previous, same))
        changed = dict(previous, answer_text="You sounded sure.")
        self.assertFalse(ecr.answer_unchanged(previous, changed))
        other_kind = dict(previous, resolution="version_written")
        self.assertFalse(ecr.answer_unchanged(previous, other_kind))
        self.assertFalse(ecr.answer_unchanged(_request(), same))  # a first answer always files
        self.assertFalse(ecr.answer_unchanged(None, same))
        db = _Db()
        ecr._file_answer(db, previous, same, {}, None, "coach-1", previous=previous)
        self.assertEqual(db.lines, [])
        ecr._file_answer(db, previous, changed, {}, None, "coach-1", previous=previous)
        self.assertEqual(len(db.lines), 1)
        self.assertEqual(db.lines[0]["text"], "You sounded sure.")
        # A clearer version never goes to the library (Q-B13 A), changed or not.
        version = dict(previous, resolution="version_written", answer_text="New words.")
        ecr._file_answer(db, previous, version, {}, None, "coach-1", previous=previous)
        self.assertEqual(len(db.lines), 1)

    def test_resolve_request_hands_the_previous_row_to_the_filing(self):
        source = inspect.getsource(ecr.resolve_request)
        self.assertIn("previous=request", source)

    def test_one_pair_per_request_is_the_table_s_own_key(self):
        sql = (ROOT / "migrations/a_coach_answers_in_words_too.sql").read_text()
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS feedback_pairs_one_per_request", sql)
        self.assertIn("ON public.feedback_pairs (surface, request_id) WHERE request_id IS NOT NULL",
                      sql)


class DoorsTests(unittest.TestCase):
    def test_a_resolved_request_is_open_to_its_coach_and_closed_to_others(self):
        self.assertFalse(changed_by_another_coach(_request(), "coach-1"))
        mine = _request(resolution="line_written", resolved_by="coach-1")
        self.assertFalse(changed_by_another_coach(mine, "coach-1"))
        self.assertTrue(changed_by_another_coach(mine, "coach-2"))
        self.assertTrue(changed_by_another_coach(mine, ""))
        self.assertFalse(changed_by_another_coach(None, "coach-1"))

    def test_the_three_doors_use_it(self):
        from services import coach_answer_video, coach_request_drafts, coach_word_pairs
        for fn in (coach_request_drafts.draft_for_request, coach_word_pairs.draft_moment_line,
                   coach_answer_video.store_answer_video):
            source = inspect.getsource(fn)
            self.assertIn("changed_by_another_coach(", source, fn.__name__)
            self.assertNotIn('if request.get("resolution"):', source)
            self.assertNotIn('if request_row.get("resolution"):', source)
        from routes.v2 import coach
        self.assertIn('coach_id=str(getattr(request, "user_id", ""))',
                      inspect.getsource(coach.v2_coach_exercise_request_video))

    def test_the_video_door(self):
        from services.coach_answer_video import store_answer_video
        mine = _request(resolution="line_written", resolved_by="coach-1", answer_text="x")
        status, payload = store_answer_video(_Db(), request_row=mine, video_file=None,
                                             max_mb=1, coach_id="coach-2")
        self.assertEqual((status, payload["code"]), (409, "ALREADY_RESOLVED"))
        status, payload = store_answer_video(_Db(), request_row=mine, video_file=None,
                                             max_mb=1, coach_id="coach-1")
        self.assertEqual((status, payload["code"]), (400, "INVALID_INPUT"))


class SpeakerCardTests(unittest.TestCase):
    def test_the_card_follows_the_row(self):
        """Q-B12 A: the speaker reads the row's current, shared answer; a
        changed shared answer replaces the card, a withdrawn share takes it
        away, and the history never rides."""
        shared = _request(resolution="line_written", answer_text="Well said.",
                          resolved_by="coach-1", shared_at="2026-10-07T20:00:00Z")
        self.assertEqual(coach_shared_answer(shared), {"kind": "line", "text": "Well said."})
        changed = dict(shared, resolution="version_written", answer_text="We think timing matters.",
                       shared_at="2026-10-07T21:00:00Z")
        self.assertEqual(coach_shared_answer(changed),
                         {"kind": "version", "text": "We think timing matters."})
        withdrawn = dict(changed, resolution="no_safe_match", answer_text=None, shared_at=None)
        self.assertIsNone(coach_shared_answer(withdrawn))
        # The speaker's payload builder reads the request row and nothing
        # about its versions.
        from services import confident_voice_practice as cvp
        self.assertNotIn("answer_versions", inspect.getsource(cvp))
        self.assertNotIn("answer_versions", (ROOT / "routes/v2/user_sessions.py").read_text())


class WallsTests(unittest.TestCase):
    def test_the_history_goes_with_the_take(self):
        from services.data_purge_registry import DEPENDENCIES
        rows = [d for d in DEPENDENCIES if d.relation == "exercise_coach_request_answer_versions"]
        self.assertEqual([(d.selector_column, d.locator_kind, d.disposition) for d in rows],
                         [("take_session_id", "take", "delete")])
        request = next(d for d in DEPENDENCIES
                       if d.relation == "exercise_coach_requests" and d.locator_kind == "take")
        self.assertLess(rows[0].delete_order, request.delete_order)

    def test_the_migration_holds_the_standing_rules(self):
        sql = (ROOT / "migrations/a_coach_may_change_their_answer.sql").read_text()
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)
        self.assertIn("REVOKE ALL ON TABLE public.exercise_coach_request_answer_versions FROM PUBLIC", sql)
        self.assertIn("REVOKE ALL ON FUNCTION public.resolve_exercise_coach_request_v3(", sql)
        self.assertIn("REVOKE ALL ON FUNCTION public.guard_exercise_coach_request_update_v2()", sql)
        self.assertIn("GRANT EXECUTE ON FUNCTION public.resolve_exercise_coach_request_v3(", sql)
        self.assertIn("SECURITY DEFINER SET search_path = public", sql)
        self.assertIn("set_config('willab.coach_answer_change', p_request_id::text, true)", sql)
        self.assertIn("Rollback (a new forward migration)", sql)
        for value in ecr.RESOLUTIONS:
            self.assertIn(f"'{value}'", sql)
