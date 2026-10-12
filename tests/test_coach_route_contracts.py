"""Route-level contracts for the coach routes moved out of
``routes/v2/coach.py`` into services (founder 2026-10-12: "move logic out of
the backend routes and cut glue").

Characterization tests, written against the unmodified routes first: each pins
one route's main success path (status, the whole JSON body, the writes and
their order) and its main refusal, so the move is provably
behaviour-preserving. Decorators (auth, rate limit, purpose guard) are peeled
with ``inspect.unwrap``; they are untouched by the move and pinned elsewhere.
"""
from __future__ import annotations

import inspect
import io
import unittest
from unittest.mock import ANY, MagicMock, patch

try:
    from flask import Flask, request

    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

UID = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
READ_SID = "33333333-3333-4333-8333-333333333333"
SID2 = "44444444-4444-4444-8444-444444444444"
ARC = "55555555-5555-4555-8555-555555555555"
ARC2 = "66666666-6666-4666-8666-666666666666"
SNIP = "77777777-7777-4777-8777-777777777777"
PRACTICE = "88888888-8888-4888-8888-888888888888"
COACH = "99999999-9999-4999-8999-999999999999"


def _call(route, *args, **ctx):
    app = Flask(__name__)
    with app.test_request_context(**ctx):
        request.user_id = COACH
        result = inspect.unwrap(route)(*args)
        resp, status = result if isinstance(result, tuple) else (result, 200)
        return status, resp.get_json()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentDetailContract(unittest.TestCase):
    """GET /v2/coach/students/<user_id>."""

    def test_the_drill_down_shape(self):
        rows = [
            {"id": SID, "take_index": 1, "intake_context": {"topic": "Board"},
             "created_at": "c1", "results_published_at": "p", "arc_id": ARC},
            {"id": READ_SID, "recording_kind": "read", "paired_session_id": SID},
            {"id": SID2, "take_index": 2, "intake_context": "junk",
             "created_at": "c2", "status": "pending_admin_review",
             "coach_feedback_saved_at": "s", "arc_id": ARC2},
        ]
        with patch.object(db, "get_user_profile", return_value={
                "domain": "sales", "goal": "g", "previous_goal": "old"}), \
                patch.object(db.takes, "v2_list_user_lab_sessions", return_value=rows), \
                patch.object(db, "get_feelings_by_sessions", return_value=[
                    {"session_id": SID, "feeling": "calm"},
                    {"session_id": SID, "feeling": "later"}]), \
                patch.object(db.ideal_text, "get_coach_arc_ideal_texts", return_value={
                    ARC: {"text": " draft ", "approved_at": None},
                    ARC2: {"text": "done", "approved_at": "a"}}) as ideal:
            status, body = _call(v2_coach.v2_coach_student_detail, UID)
        self.assertEqual(status, 200)
        ideal.assert_called_once_with([ARC, ARC2])
        self.assertEqual(body, {
            "pseudonym": v2_coach._coach_pseudonym(UID),
            "domain": "sales", "goal": "g", "ideal_ready_arc_ids": [ARC],
            "previous_goal": "old", "goal_changed_at": "",
            "sessions": [
                {"session_id": SID, "take_index": 1, "topic": "Board",
                 "created_at": "c1", "state": "insights_ready",
                 "review_state": "delivered", "arc_id": ARC,
                 "feeling": "calm", "has_reread": True},
                {"session_id": SID2, "take_index": 2, "topic": "",
                 "created_at": "c2", "state": "review_pending",
                 "review_state": "reviewed", "arc_id": ARC2,
                 "feeling": None, "has_reread": False},
            ],
        })

    def test_refusals(self):
        status, body = _call(v2_coach.v2_coach_student_detail, "nope")
        self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
        with patch.object(db, "get_user_profile", return_value=None), \
                patch.object(db.takes, "v2_list_user_lab_sessions", return_value=[]):
            status, body = _call(v2_coach.v2_coach_student_detail, UID)
        self.assertEqual((status, body["code"]), (404, "STUDENT_NOT_FOUND"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PracticeReviewContract(unittest.TestCase):
    """PUT /v2/coach/sessions/<sid>/snippets/<snip>/confidence-practice."""

    def _gate(self, rating):
        return [
            patch.object(db, "v2_get_session_by_id", return_value={"id": SID}),
            patch.object(v2_coach, "_snippet_owner_map", return_value={SNIP: SID}),
            patch.object(v2_coach, "_coach_state_map",
                         return_value={SNIP: {"rating_value": rating}}),
            patch.object(v2_coach, "_speaker_practice_permitted", return_value=True),
        ]

    def test_the_blind_gate_refuses_first(self):
        with self._gate(None)[0], self._gate(None)[1], self._gate(None)[2], \
                patch.object(db, "get_confident_voice_practice_by_moment") as read:
            status, body = _call(
                v2_coach.v2_coach_confident_voice_practice, SID, SNIP,
                method="PUT", json={"professional_coach_decision": "yes"})
        self.assertEqual((status, body["code"]), (409, "BLIND_RATING_REQUIRED"))
        read.assert_not_called()

    def test_a_shared_decision_writes_in_order(self):
        practice = {"id": PRACTICE, "snippet_id": SNIP, "exercise_id": "ex-1",
                    "selected_attempt_id": "att-1", "owner_user_id": UID,
                    "project_id": ARC}
        exercise = {"exercise_id": "ex-1", "version": 2, "title": "T",
                    "instruction": "I", "explanation_video_url": "https://lib/v"}
        rec = MagicMock()
        rec.update.side_effect = [dict(practice, updated=True), {"chat": True}]
        rec.attempt.return_value = {"id": "att-1"}
        rec.share.return_value = {"id": "assign-1"}
        rec.reconcile.return_value = True
        rec.shared.return_value = True
        gate = self._gate("yes")
        with gate[0], gate[1], gate[2], gate[3], \
                patch.object(db, "get_confident_voice_practice_by_moment",
                             return_value=practice), \
                patch.object(db, "get_active_diagnostic_exercise", return_value=exercise), \
                patch.object(db, "set_confident_voice_practice_attempt_coach_decision",
                             rec.attempt), \
                patch.object(db, "record_practice_more_confident", rec.more), \
                patch.object(db, "update_confident_voice_practice", rec.update), \
                patch.object(db, "teach_diagnostic_exercise", rec.teach), \
                patch("services.coach_moment_errors.moment_teaching",
                      return_value=(["err-1"], "coach")), \
                patch("services.confident_voice_practice.record_coach_review_share",
                      rec.share), \
                patch("services.confident_voice_practice.reconcile_practice_voice_album",
                      rec.reconcile), \
                patch("services.arc_notifications.fire_voice_album_ready", rec.album), \
                patch("services.arc_notifications.fire_confidence_practice_shared",
                      rec.shared), \
                patch.object(v2_coach, "_coach_practice_payload",
                             side_effect=lambda p: {"payload_of": p.get("id"),
                                                    "updated": p.get("updated")}):
            status, body = _call(
                v2_coach.v2_coach_confident_voice_practice, SID, SNIP,
                method="PUT", json={
                    "professional_coach_decision": "yes",
                    "selected_attempt_coach_decision": "yes",
                    "share_with_user": True, "own_wording": True,
                    "explanation_video_url": " https://coach/v "})
        self.assertEqual(status, 200, body)
        self.assertEqual(body, {"practice": {"payload_of": PRACTICE, "updated": True}})
        snapshot = {"exercise_id": "ex-1", "version": 2, "title": "T",
                    "instruction": "I", "explanation_video_url": "https://coach/v",
                    "source": "diagnostic_library", "own_wording": True,
                    "exercise_assignment_id": "assign-1"}
        self.assertEqual([c[0] for c in rec.mock_calls], [
            "share", "attempt", "more", "update", "reconcile", "album", "teach",
            "shared", "update"])
        rec.attempt.assert_called_once_with(PRACTICE, "att-1", "yes", COACH)
        self.assertEqual(rec.update.call_args_list[0].args, (PRACTICE, None, {
            "professional_coach_decision": "yes",
            "coach_selected_exercise_id": "ex-1",
            "coach_custom_exercise": None,
            "coach_explanation_video_url": "https://coach/v",
            "coach_shared_exercise": snapshot,
            "coach_shared_by": COACH,
            "coach_shared_at": ANY,
        }))
        self.assertEqual(rec.update.call_args_list[1].args,
                         (PRACTICE, None, {"chat_emitted_at": ANY}))
        rec.teach.assert_called_once_with("ex-1", PRACTICE, COACH, ["err-1"], "coach")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SessionVideoContract(unittest.TestCase):
    """POST /v2/coach/sessions/<sid>/video."""

    def _post(self, filename="clip.MP4", payload=b"abc", form=None):
        data = {"video_file": (io.BytesIO(payload), filename), **(form or {})}
        return _call(v2_coach.v2_coach_session_video, SID, method="POST",
                     data=data, content_type="multipart/form-data")

    def test_a_stored_video(self):
        uuid_obj = MagicMock(hex="abc123")
        with patch.object(db, "v2_get_session_by_id", return_value={"id": SID}), \
                patch("services.coach_video_storage.default_media_bucket",
                      return_value="bkt"), \
                patch("services.coach_video_storage.put_coach_object_bytes") as put, \
                patch("services.coach_video_storage.presigned_get_coach_object",
                      side_effect=lambda b, k, **kw: f"https://signed/{b}/{k}"), \
                patch("uuid.uuid4", return_value=uuid_obj), \
                patch.object(db.takes, "set_session_coach_video_ref") as setref:
            status, body = self._post()
        self.assertEqual(status, 200, body)
        key = f"coach-feedback/{SID}/abc123.mp4"
        put.assert_called_once_with("bkt", key, b"abc", ANY)
        setref.assert_called_once_with(SID, f"s3://bkt/{key}")
        self.assertEqual(body, {"status": "ok", "session_id": SID,
                                "video_ref": f"https://signed/bkt/{key}"})

    def test_refusals(self):
        with patch.object(db, "v2_get_session_by_id", return_value=None):
            status, body = self._post()
        self.assertEqual((status, body["code"]), (404, "SESSION_NOT_FOUND"))
        with patch.object(db, "v2_get_session_by_id", return_value={"id": SID}):
            status, body = self._post(filename="clip.avi")
            self.assertEqual((status, body["code"]), (415, "INVALID_VIDEO_FORMAT"))
            status, body = self._post(payload=b"")
            self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
            with patch.object(db, "get_coach_video_asset_by_idempotency_key",
                              return_value={"video_ref": "https://x/y"}), \
                    patch.object(db.takes, "set_session_coach_video_ref") as setref:
                status, body = self._post(form={"upload_idempotency_key": "k"})
            self.assertEqual(status, 200)
            self.assertTrue(body["deduped"])
            setref.assert_called_once_with(SID, "https://x/y")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ExerciseVideoContract(unittest.TestCase):
    """POST /v2/coach/exercises/<id>/video (the same upload checks)."""

    def _post(self, filename="clip.mov", form=None):
        from routes.v2 import coach_exercises
        data = {"video_file": (io.BytesIO(b"vid"), filename), **(form or {})}
        return _call(coach_exercises.v2_coach_exercise_video, "ex-1",
                     method="POST", data=data, content_type="multipart/form-data")

    def test_the_upload_reaches_the_library(self):
        with patch("services.coach_exercise_authoring.attach_video",
                   return_value=(200, {"exercise": "ex-1"})) as attach:
            status, body = self._post(form={"exercise": '{"title": "T"}'})
        self.assertEqual((status, body), (200, {"exercise": "ex-1"}))
        attach.assert_called_once_with(
            db, exercise_id="ex-1", coach_id=COACH, video_bytes=b"vid",
            filename="clip.mov", content_type=ANY, definition={"title": "T"})

    def test_refusals(self):
        with patch("services.coach_exercise_authoring.attach_video") as attach:
            status, body = self._post(form={"exercise": "{"})
            self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
            status, body = self._post(filename="clip.gif")
            self.assertEqual((status, body["code"]), (415, "INVALID_VIDEO_FORMAT"))
        attach.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TrainingImportContract(unittest.TestCase):
    """POST /v2/coach/training-imports."""

    FORM = {"topic": " Board ", "language": "pl", "speaker_label": " Ann ",
            "idempotency_key": " k1 ", "queue_per_band": "x"}

    def _post(self, form):
        data = {"audio_file": (io.BytesIO(b"aud"), "talk.webm"), **form}
        return _call(v2_coach.v2_coach_training_import, method="POST",
                     data=data, content_type="multipart/form-data")

    def test_a_receipt_then_the_background_analysis(self):
        prepared = {"ok": True, "session_id": SID, "arc_id": ARC,
                    "recording_id": "rec-1", "stages": ["confidence"],
                    "duration_sec": 12, "speaker_label": "Ann", "language": "pl"}
        with patch("services.training_import.prepare_training_import",
                   return_value=prepared) as prep, \
                patch("services.training_import.run_training_import_analysis") as run, \
                patch("services.processing_authorization.register_corpus_import") as reg, \
                patch("threading.Thread") as thread:
            status, body = self._post(self.FORM)
        self.assertEqual(status, 202, body)
        prep.assert_called_once_with(
            audio_bytes=b"aud", filename="talk.webm", content_type=ANY,
            user_id=COACH, topic="Board", speaker_label="Ann", source_note=None,
            stages=None, idempotency_key="k1", language="pl")
        reg.assert_called_once_with(db, session_id=SID, recording_id="rec-1")
        thread.assert_called_once_with(
            target=run, kwargs={"prepared": prepared, "audio_bytes": b"aud",
                                "filename": "talk.webm", "queue_per_band": 5},
            daemon=True)
        thread.return_value.start.assert_called_once_with()
        self.assertEqual(body, {
            "ok": True, "status": "processing", "session_id": SID,
            "arc_id": ARC, "stages": ["confidence"], "duration_sec": 12,
            "speaker_label": "Ann", "language": "pl", "filename": "talk.webm"})

    def test_refusals(self):
        status, body = self._post({"language": "pl"})
        self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
        with patch("services.training_import.prepare_training_import",
                   return_value={"ok": False, "reason": "silence"}):
            status, body = self._post(self.FORM)
        self.assertEqual((status, body["code"], body["reason"]),
                         (422, "AUDIO_REJECTED", "silence"))
        from services.processing_authorization import ProcessingAuthorizationError
        with patch("services.training_import.prepare_training_import",
                   return_value={"ok": True, "session_id": SID, "arc_id": ARC}), \
                patch("services.processing_authorization.register_corpus_import",
                      side_effect=ProcessingAuthorizationError("CORPUS_BASIS_ABSENT", "m", 409)), \
                patch.object(db.takes, "set_session_analysis_state") as failed, \
                patch("threading.Thread") as thread:
            status, body = self._post(self.FORM)
        self.assertEqual((status, body["code"]), (409, "CORPUS_BASIS_ABSENT"))
        failed.assert_called_once_with(SID, "failed", error="CORPUS_BASIS_ABSENT")
        thread.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ConfidenceLabelContract(unittest.TestCase):
    """PUT /v2/coach/snippets/<snip>/confidence-label: the refusals (the
    success path is pinned by test_training_import_on)."""

    def test_refusals(self):
        status, body = _call(v2_coach.v2_coach_put_confidence_label, "nope",
                             method="PUT", json={})
        self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
        with patch.object(db, "get_snippet_by_id", return_value=None):
            status, body = _call(v2_coach.v2_coach_put_confidence_label, SNIP,
                                 method="PUT", json={"state_id": "confidence",
                                                     "value": "yes"})
        self.assertEqual((status, body["code"]), (404, "NOT_FOUND"))
        snip = {"id": SNIP, "session_id": SID}
        with patch.object(db, "get_snippet_by_id", return_value=snip), \
                patch.object(db, "v2_get_session_by_id",
                             return_value={"id": SID, "user_id": UID}), \
                patch.object(v2_coach, "_session_shows_slides", return_value=False), \
                patch.object(v2_coach, "_rater_language_outcome",
                             return_value=("matched", "en")), \
                patch.object(db, "get_confidence_labels_by_snippet_ids", return_value={
                    SNIP: [{"rater_id": "other", "value": "audio_unclear",
                            "unrateable": True, "lane": "coach"}]}), \
                patch("services.label_quorum.rater_submission_access",
                      return_value={"allowed": False,
                                    "outcome": "fresh_rater_required"}), \
                patch.object(db, "upsert_state_rating") as write:
            status, body = _call(v2_coach.v2_coach_put_confidence_label, SNIP,
                                 method="PUT", json={"confident": True})
        self.assertEqual((status, body["code"]), (409, "FRESH_RATER_REQUIRED"))
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
