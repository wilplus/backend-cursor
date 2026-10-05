"""An exercise keeps its versions (founder 2026-09-29, decision 4; 0399).

Pins:
  * a save that changes the definition or the video bumps the live row's
    version; a save that changes nothing keeps it; a new exercise starts
    at the version asked for, never below 1;
  * every save through the catalogue writes one version row with its source,
    the AI draft beside the final, the video lineage and the transcript's
    state; a version that cannot be written never costs the save;
  * the coach's video is transcribed under the coach's own authorization:
    no principal while the boundary is enforced, or a refused permit, is
    recorded as coach_authorization_missing, a provider failure as failed,
    and a transcript as done with its language;
  * the transcript's arrival is one call on a pending row.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import exercise_versions as ev
from services.diagnostic_exercise_catalogue import save_exercise

LIBRARY = [{"error_id": "rushing", "status": "detected", "active": True},
           {"error_id": "ending_compression", "status": "detected", "active": True}]
MAIN = {"primary_problem_tag": "ending_compression"}


def _row(**over):
    base = {"exercise_id": "land-it", "title": "Land the ending",
            "instruction": "Say the last word fully.",
            "introduction_copy": "", "explanation_video_url": "https://cdn.example/a.mp4",
            "acoustic_problem_tags": ["ending_compression"],
            "supported_confidence_patterns": ["near_confident"],
            "matching_criteria": {}, "version": 1, "active": True}
    base.update(over)
    return base


class _Db:
    def __init__(self, existing=None):
        self.rows = {existing["exercise_id"]: dict(existing)} if existing else {}
        self.versions = []
        self.settled = []
        self.fail_versions = False

    def list_speaking_errors(self, active_only=True):
        return LIBRARY

    def get_journal_post_by_id(self, post_id):
        return {"status": "published"}

    def get_diagnostic_exercise(self, exercise_id):
        return dict(self.rows[exercise_id]) if exercise_id in self.rows else None

    def upsert_diagnostic_exercise(self, row):
        self.rows[row["exercise_id"]] = dict(row)
        return dict(row)

    def record_exercise_version(self, payload):
        if self.fail_versions:
            raise RuntimeError("PGRST202 function not found")
        self.versions.append(payload)
        return {"id": f"v-{len(self.versions)}", **payload}

    def set_exercise_version_transcript(self, **kwargs):
        self.settled.append(kwargs)
        return {"transcript_status": kwargs["status"]}


class VersionRuleTests(unittest.TestCase):
    def test_a_new_exercise_starts_at_the_version_asked_for_never_below_one(self):
        self.assertEqual(ev.next_version(None, _row(version=3)), 3)
        self.assertEqual(ev.next_version(None, _row(version=0)), 1)
        self.assertEqual(ev.next_version(None, {"title": "x"}), 1)

    def test_a_changed_definition_bumps_and_an_unchanged_one_keeps(self):
        before = _row(version=4)
        self.assertEqual(ev.next_version(before, _row(version=1)), 4)
        self.assertEqual(ev.next_version(before, _row(instruction="Slower.")), 5)
        self.assertEqual(ev.next_version(before, _row(
            explanation_video_url="https://cdn.example/b.mp4")), 5)
        self.assertEqual(ev.next_version(before, _row(
            acoustic_problem_tags=["rushing", "ending_compression"])), 5)

    def test_order_of_tags_and_missing_optional_text_are_not_changes(self):
        before = _row(acoustic_problem_tags=["rushing", "ending_compression"],
                      confident_introduction_copy=None)
        after = _row(acoustic_problem_tags=["ending_compression", "rushing"])
        after.pop("confident_introduction_copy", None)
        self.assertFalse(ev.definition_changed(before, after))


class CatalogueVersioningTests(unittest.TestCase):
    def test_every_save_writes_one_version_row_with_its_source(self):
        db = _Db()
        # A new coach exercise names its main error (E5, W6 2026-10-05).
        saved = save_exercise(db, _row(matching_criteria=MAIN), source="coach_panel",
                              created_by="coach-1",
                              ai_draft_text="Draft words", ai_draft_model_version="m1")
        self.assertEqual(saved["version"], 1)
        self.assertEqual(len(db.versions), 1)
        row = db.versions[0]
        self.assertEqual((row["exercise_id"], row["version"], row["source"],
                          row["created_by"]), ("land-it", 1, "coach_panel", "coach-1"))
        self.assertEqual(row["ai_draft_text"], "Draft words")
        self.assertEqual(row["ai_draft_model_version"], "m1")
        self.assertEqual(row["transcript_status"], "not_requested")
        self.assertEqual(row["acoustic_problem_tags"], ["ending_compression"])

    def test_an_edit_bumps_the_live_row_and_a_no_op_save_does_not(self):
        db = _Db()
        save_exercise(db, _row())
        again = save_exercise(db, _row())
        self.assertEqual(again["version"], 1)
        edited = save_exercise(db, _row(instruction="Slower, and land it."))
        self.assertEqual(edited["version"], 2)
        self.assertEqual([v["version"] for v in db.versions], [1, 1, 2])
        self.assertEqual(db.versions[-1]["source"], "cms")

    def test_the_video_lineage_and_transcript_state_ride_the_version(self):
        db = _Db(existing=_row(version=2))
        saved = save_exercise(db, _row(explanation_video_url="https://cdn.example/new.mp4"),
                              source="coach_panel", video_sha256="a" * 64,
                              video_bytes=1234, transcript_status="pending")
        self.assertEqual(saved["version"], 3)
        row = db.versions[0]
        self.assertEqual(row["video_sha256"], "a" * 64)
        self.assertEqual(row["video_bytes"], 1234)
        self.assertEqual(row["transcript_status"], "pending")
        self.assertEqual(row["explanation_video_url"], "https://cdn.example/new.mp4")

    def test_a_version_that_cannot_be_written_never_costs_the_save(self):
        db = _Db()
        db.fail_versions = True
        saved = save_exercise(db, _row())
        self.assertEqual(saved["exercise_id"], "land-it")
        self.assertEqual(db.versions, [])

    def test_an_unknown_source_is_a_bug_not_a_row(self):
        with self.assertRaises(ValueError):
            ev.record_version(_Db(), _row(), source="somewhere")

    def test_the_answered_call_files_under_its_own_source(self):
        from services.diagnostic_exercise_catalogue import file_coach_exercise
        db = _Db()
        file_coach_exercise(db, practice_id="p1", fields=_row(matching_criteria=MAIN))
        self.assertEqual(db.versions[0]["source"], "coach_review")
        self.assertEqual(db.versions[0]["exercise_id"], "coach-custom-p1")


class _Adapter:
    calls: list = []

    def __init__(self, database, coordinates, *, authorization):
        self.coordinates = coordinates
        _Adapter.calls.append(coordinates)

    def transcribe_snippet(self, audio_bytes, hint_filename, *, language_hint=None):
        return _Adapter.answer


class _Authorization:
    enforced = False

    def __init__(self, database):
        pass


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        _Adapter.calls = []
        _Adapter.answer = {"transcript": "Land the ending.", "language": "en",
                           "words": []}

    def _run(self, db, enforced=False):
        class Auth(_Authorization):
            pass
        Auth.enforced = enforced
        with patch("services.authorized_provider.AuthorizedProviderAdapter", _Adapter), \
                patch("services.processing_authorization.ProcessingAuthorizationService", Auth):
            return ev.transcribe_exercise_video(
                db, coach_user_id="coach-1", video_bytes=b"x", filename="a.mp4")

    def test_a_transcript_is_done_with_its_language_under_the_coach_s_principal(self):
        db = _Db()
        db.get_owner_principal_for_user = lambda uid: {"id": "principal-coach"}
        status, transcript, language = self._run(db)
        self.assertEqual(status, "done")
        self.assertEqual(transcript["transcript"], "Land the ending.")
        self.assertEqual(language, "en")
        self.assertEqual(_Adapter.calls[0].acquisition_principal_id, "principal-coach")
        self.assertIsNone(_Adapter.calls[0].take_id)

    def test_no_principal_while_enforced_is_recorded_not_raised(self):
        db = _Db()
        db.get_owner_principal_for_user = lambda uid: None
        status, transcript, _ = self._run(db, enforced=True)
        self.assertEqual(status, "coach_authorization_missing")
        self.assertIsNone(transcript)
        self.assertEqual(_Adapter.calls, [])

    def test_a_refused_permit_is_recorded_as_missing_authorization(self):
        from services.processing_authorization import ProcessingAuthorizationError

        def refuse(*_a, **_k):
            raise ProcessingAuthorizationError("PROCESSING_NOT_AUTHORIZED", "no", 403)
        db = _Db()
        db.get_owner_principal_for_user = lambda uid: {"id": "p"}
        with patch.object(_Adapter, "transcribe_snippet", refuse):
            status, _, _ = self._run(db)
        self.assertEqual(status, "coach_authorization_missing")

    def test_a_provider_failure_or_an_empty_answer_is_failed(self):
        db = _Db()
        db.get_owner_principal_for_user = lambda uid: {"id": "p"}
        _Adapter.answer = None
        self.assertEqual(self._run(db)[0], "failed")

        def boom(*_a, **_k):
            raise RuntimeError("network")
        with patch.object(_Adapter, "transcribe_snippet", boom):
            self.assertEqual(self._run(db)[0], "failed")

    def test_the_transcript_s_arrival_is_one_call_on_the_pending_row(self):
        db = _Db()
        ev.settle_transcript(db, exercise_id="land-it", version=2, status="done",
                             transcript={"transcript": "x"}, language="en")
        self.assertEqual(db.settled[0], {"exercise_id": "land-it", "version": 2,
                                         "status": "done",
                                         "transcript": {"transcript": "x"},
                                         "language": "en"})
