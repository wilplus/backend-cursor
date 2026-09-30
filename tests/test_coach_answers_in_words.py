"""A coach answers in words too (founder 2026-09-30, C2 to C5; migration
0402; build plan P2-3, P2-4, P2-7).

Pins:
  * a praise request resolved as `line_written` and a rewrite as
    `version_written` carry `answer_text`, share like an exercise, and ride
    the speaker's row as `coach_answer` when shared (never the draft);
  * a praise line lands in the catalogue of signed lines for the moment's
    pattern unless the coach keeps it; a clearer version never does;
  * where a draft was shown and the final differs, one pair is recorded on
    the answer's surface, with the coach as author;
  * an authored exercise names its main target or is refused;
  * a pattern can be named on the moment itself, without a practice row.
"""
from __future__ import annotations

import pathlib
import unittest

from services import coach_moment_errors as cme
from services import exercise_coach_requests as ecr
from services.confident_voice_practice import coach_shared_answer

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self, request):
        self.request = request
        self.resolved = []
        self.pairs = []
        self.lines = []
        self.saved = []

    def list_speaking_errors(self, active_only=True):
        return [{"error_id": "hedging", "label": "Hedging", "active": True,
                 "detected_by": ["verbal-cues-v1"]}]

    def get_confident_voice_exercise_assignment(self, _t, _s):
        return None

    def list_diagnostic_exercises(self):
        return []

    def get_diagnostic_exercise(self, _id):
        return None

    def get_active_diagnostic_exercise(self, _id):
        return None

    def upsert_diagnostic_exercise(self, row):
        self.saved.append(row)
        return {**row, "version": 1}

    def record_exercise_version(self, payload):
        return payload

    def resolve_exercise_coach_request(self, **kwargs):
        self.resolved.append(kwargs)
        return {**self.request, "resolution": kwargs["resolution"],
                "answer_text": kwargs.get("answer_text"),
                "resolved_exercise_id": kwargs.get("exercise_id"),
                "shared_at": "now" if kwargs["share"] else None}

    def insert_feedback_pair(self, **fields):
        self.pairs.append(fields)
        return {"id": "pair-1", **fields}

    def create_admin_annotation_event(self, **fields):
        pass

    def insert_feedback_catalogue_line(self, **fields):
        self.lines.append(fields)
        return {"id": "line-1", **fields}


def _request(kind, **extra):
    return {"id": "req-1", "take_session_id": "take-1", "snippet_id": "snip-1",
            "owner_user_id": "owner-1", "kind": kind, "observed_tags": ["hedging"],
            "reason": "judgement", "resolution": None, "request_trace": {"why_key": "clarity"},
            **extra}


class WordsTests(unittest.TestCase):
    def test_a_praise_line_is_answered_shared_and_filed(self):
        db = _Db(_request("praise", draft_text="You sounded sure.",
                          draft_surface="praise_line", draft_model_version="m"))
        status, payload = ecr.resolve_request(
            db, db.request, {"resolution": "line_written",
                             "answer_text": "You let the  number land.",
                             "share_with_user": True}, coach_id="coach-1")
        self.assertEqual(status, 200, payload)
        self.assertEqual(db.resolved[0]["answer_text"], "You let the number land.")
        self.assertEqual(payload["request"]["answer_text"], "You let the number land.")
        self.assertEqual(payload["request"]["draft"]["text"], "You sounded sure.")
        self.assertEqual(db.pairs[0]["surface"], "praise_line")
        self.assertEqual(db.pairs[0]["coach_id"], "coach-1")
        self.assertEqual(db.pairs[0]["owner_user_id"], "owner-1")
        self.assertEqual(db.lines[0]["lane"], "praise")
        self.assertEqual((db.lines[0]["pattern_kind"], db.lines[0]["pattern_key"]),
                         ("cue", "hedging"))
        self.assertEqual(db.lines[0]["signed_by"], "coach-1")

    def test_a_line_the_coach_keeps_to_the_speaker_is_not_filed(self):
        db = _Db(_request("praise"))
        status, _ = ecr.resolve_request(
            db, db.request, {"resolution": "line_written", "answer_text": "Clear.",
                             "file_in_catalogue": False}, coach_id="c")
        self.assertEqual(status, 200)
        self.assertEqual(db.lines, [])
        self.assertEqual(db.pairs, [])  # no draft was shown

    def test_a_clearer_version_never_becomes_a_catalogue_move(self):
        db = _Db(_request("rewrite", draft_text="We cut tickets by a third.",
                          draft_surface="clearer_version"))
        status, payload = ecr.resolve_request(
            db, db.request, {"resolution": "version_written",
                             "answer_text": "The new flow cut tickets by a third.",
                             "share_with_user": True}, coach_id="c")
        self.assertEqual(status, 200)
        self.assertEqual(db.lines, [])
        self.assertEqual(db.pairs[0]["surface"], "clearer_version")
        self.assertEqual(db.pairs[0]["pattern_key"], "clarity")

    def test_an_unchanged_final_makes_no_pair(self):
        db = _Db(_request("praise", draft_text="Same.", draft_surface="praise_line"))
        ecr.resolve_request(db, db.request, {"resolution": "line_written",
                                             "answer_text": "Same."}, coach_id="c")
        self.assertEqual(db.pairs, [])

    def test_words_need_words(self):
        db = _Db(_request("praise"))
        status, payload = ecr.resolve_request(
            db, db.request, {"resolution": "line_written", "answer_text": "  "}, coach_id="c")
        self.assertEqual((status, payload["code"]), (400, "INVALID_INPUT"))

    def test_the_shared_answer_rides_the_speaker_row_and_the_draft_does_not(self):
        answer = coach_shared_answer({"resolution": "version_written", "shared_at": "now",
                                      "answer_text": "Said  plainly.", "draft_text": "x"})
        self.assertEqual(answer, {"kind": "version", "text": "Said plainly."})
        self.assertIsNone(coach_shared_answer({"resolution": "version_written",
                                               "shared_at": None, "answer_text": "a"}))
        self.assertIsNone(coach_shared_answer({"resolution": "exercise_chosen",
                                               "shared_at": "now", "answer_text": None}))

    def test_a_note_rides_the_moment_and_is_never_filed(self):
        db = _Db(_request("ambiguity", draft_text=None))
        status, payload = ecr.resolve_request(
            db, db.request, {"resolution": "note_written",
                             "answer_text": "You and the machine disagree; listen again.",
                             "share_with_user": True}, coach_id="c")
        self.assertEqual(status, 200, payload)
        self.assertEqual(db.lines, [])
        self.assertEqual(db.pairs, [])
        answer = coach_shared_answer({**db.request, "resolution": "note_written",
                                      "shared_at": "now", "answer_text": "Listen again.",
                                      "answer_video_ref": "https://v/note.mp4"})
        self.assertEqual(answer, {"kind": "note", "text": "Listen again.",
                                  "video_url": "https://v/note.mp4"})

    def test_the_coach_s_own_pattern_choice_files_the_line(self):
        db = _Db(_request("praise"))
        ecr.resolve_request(db, db.request, {"resolution": "line_written",
                                             "answer_text": "You opened strong.",
                                             "pattern_key": "opened_strong"}, coach_id="c")
        self.assertEqual((db.lines[0]["pattern_kind"], db.lines[0]["pattern_key"]),
                         ("cue", "opened_strong"))
        db = _Db(_request("praise"))
        ecr.resolve_request(db, db.request, {"resolution": "line_written",
                                             "answer_text": "You sounded sure.",
                                             "pattern_key": "confident_read"}, coach_id="c")
        self.assertEqual((db.lines[0]["pattern_kind"], db.lines[0]["pattern_key"]),
                         ("read", "confident_read"))

    def test_the_resolution_values_match_the_migration(self):
        sql = (ROOT / "migrations/a_word_for_this_take.sql").read_text()
        for value in ecr.RESOLUTIONS:
            self.assertIn(f"'{value}'", sql)
        self.assertIn("resolve_exercise_coach_request_v2", sql)
        pairs = (ROOT / "migrations/a_coach_answers_in_words_too.sql").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS public.feedback_pairs", pairs)
        self.assertIn("ALTER TABLE public.feedback_pairs ENABLE ROW LEVEL SECURITY", pairs)


class MainTargetTests(unittest.TestCase):
    def test_an_authored_exercise_without_a_main_target_is_refused(self):
        db = _Db(_request("error"))
        status, payload = ecr.resolve_request(
            db, db.request, {"resolution": "exercise_authored",
                             "custom_exercise": {"title": "Land it", "instruction": "Say it once.",
                                                 "explanation_video_url": "https://v/x.mp4"}},
            coach_id="c")
        self.assertEqual((status, payload["code"]), (400, "MAIN_TARGET_REQUIRED"))
        self.assertEqual(db.saved, [])

    def test_main_target_shorthand_becomes_the_primary_tag(self):
        fields = {"acoustic_problem_tags": ["filler_cluster"], "main_target": "hedging"}
        self.assertIsNone(ecr._require_main_target(fields))
        self.assertEqual(fields["matching_criteria"]["primary_problem_tag"], "hedging")
        self.assertEqual(fields["acoustic_problem_tags"], ["hedging", "filler_cluster"])
        self.assertNotIn("main_target", fields)

    def test_an_authored_exercise_pairs_its_script_with_the_draft(self):
        db = _Db(_request("error", draft_text="Draft script.", draft_surface="exercise_script",
                          draft_model_version="m"))
        exercise = {"exercise_id": "coach-request-req-1", "version": 1,
                    "instruction": "Final script."}
        ecr._file_answer(db, db.request, {**db.request, "resolution": "exercise_authored"},
                         {}, exercise, "coach-1")
        self.assertEqual(db.pairs[0]["surface"], "exercise_script")
        self.assertEqual(db.pairs[0]["exercise_id"], "coach-request-req-1")
        self.assertEqual(db.pairs[0]["final_text"], "Final script.")


class _MomentDb:
    def __init__(self):
        self.events = []

    def get_speaking_error(self, error_id):
        return {"error_id": error_id, "active": error_id != "retired"}

    def list_coach_moment_error_events_for_snippet(self, snippet_id):
        return [e for e in self.events if e["snippet_id"] == snippet_id]

    def insert_coach_moment_error_event(self, practice_id, error_id, coach_id, action, *,
                                        snippet_id=None, take_session_id=None):
        row = {"practice_id": practice_id, "error_id": error_id, "coach_id": coach_id,
               "action": action, "snippet_id": snippet_id, "take_session_id": take_session_id}
        self.events.append(row)
        return row


class NamedOnMomentTests(unittest.TestCase):
    def test_naming_withdrawing_and_idempotence_on_the_moment(self):
        db = _MomentDb()
        status, payload = cme.name_error_on_moment(
            db, take_session_id="take-1", snippet_id="snip-1",
            body={"error_id": "hedging"}, coach_id="c")
        self.assertEqual((status, payload), (200, {"named": ["hedging"]}))
        self.assertIsNone(db.events[0]["practice_id"])
        self.assertEqual(db.events[0]["take_session_id"], "take-1")
        cme.name_error_on_moment(db, take_session_id="take-1", snippet_id="snip-1",
                                 body={"error_id": "hedging", "named": True}, coach_id="c")
        self.assertEqual(len(db.events), 1)
        status, payload = cme.name_error_on_moment(
            db, take_session_id="take-1", snippet_id="snip-1",
            body={"error_id": "hedging", "named": False}, coach_id="c")
        self.assertEqual(payload, {"named": []})
        self.assertEqual(cme.named_errors_on_moment(db, "snip-1"), [])

    def test_only_a_library_entry_can_be_named(self):
        status, payload = cme.name_error_on_moment(
            _MomentDb(), take_session_id="t", snippet_id="s",
            body={"error_id": "retired"}, coach_id="c")
        self.assertEqual((status, payload["code"]), (404, "ERROR_NOT_IN_LIBRARY"))


if __name__ == "__main__":
    unittest.main()
