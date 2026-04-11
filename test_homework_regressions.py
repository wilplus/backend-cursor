import unittest

try:
    from flask import Flask
    _FLASK_IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    _FLASK_IMPORT_ERROR = import_err


try:
    from routes import homework as hw
    _HW_IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    hw = None
    _HW_IMPORT_ERROR = import_err

try:
    from services import db as db_module
    _DB_IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    db_module = None
    _DB_IMPORT_ERROR = import_err


@unittest.skipIf(
    _HW_IMPORT_ERROR is not None or _FLASK_IMPORT_ERROR is not None,
    f"homework tests require full app deps: hw={_HW_IMPORT_ERROR} flask={_FLASK_IMPORT_ERROR}",
)
class HomeworkRouteRegressionsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_self_rating_completes_from_task_block_when_recording_finished(self):
        original_v2_get_session = hw.db.v2_get_session
        original_update_or_set = hw.db.update_or_set_session_sniper_rating
        original_v2_update_session = hw.db.v2_update_session
        original_get_sniper_profile_payload = hw.db.get_sniper_profile_payload
        original_complete = hw.complete_session_recording_1_only
        try:
            called = {"allow_task_block": None}

            hw.db.v2_get_session = lambda _sid, _uid: {
                "id": "s1",
                "status": hw.STATUS_TASK_BLOCK,
                "recording_1_id": "r1",
                "recording_1_processing_status": "completed",
            }
            hw.db.update_or_set_session_sniper_rating = lambda *_args, **_kwargs: True
            hw.db.v2_update_session = lambda *_args, **_kwargs: True
            hw.db.get_sniper_profile_payload = lambda _uid: {"realtime_level": 1, "realtime_step": 1}

            def _fake_complete(session_id, user_id, allow_task_block=False, preferred_student_email=None):
                called["allow_task_block"] = allow_task_block
                return {"session_id": session_id, "user_id": user_id, "ok": True}

            hw.complete_session_recording_1_only = _fake_complete

            with self.app.test_request_context("/v2/homework/session/s1/self-rating", method="POST", json={"rating": 4}):
                hw.request.user_id = "u1"
                hw.request.token_payload = {"email": "student@example.com"}
                response, status = hw.homework_self_rating.__wrapped__("s1")

            payload = response.get_json()
            self.assertEqual(status, 200)
            self.assertTrue(payload["session_completed"])
            self.assertEqual(payload["rating"], 4)
            self.assertTrue(called["allow_task_block"])
        finally:
            hw.db.v2_get_session = original_v2_get_session
            hw.db.update_or_set_session_sniper_rating = original_update_or_set
            hw.db.v2_update_session = original_v2_update_session
            hw.db.get_sniper_profile_payload = original_get_sniper_profile_payload
            hw.complete_session_recording_1_only = original_complete

    def test_get_report_uses_score_fallback_when_score_for_display_missing(self):
        original_v2_get_session = hw.db.v2_get_session
        original_get_recording_for_homework_session = hw.db.get_recording_for_homework_session
        original_v2_get_performance_history = hw.db.v2_get_performance_history
        original_get_sniper_profile_payload = hw.db.get_sniper_profile_payload
        original_get_session_sniper_metrics = hw.db.get_session_sniper_metrics
        original_ensure_student_completion_email = hw.ensure_student_completion_email
        original_backfill = hw.best_effort_backfill_recording_1_transcript
        try:
            hw.db.v2_get_session = lambda _sid, _uid: {
                "id": "s1",
                "status": hw.STATUS_COMPLETED,
                "context_long": "Report body",
                "report_id": None,
                "score": 0.73,
                "score_for_display": None,
                "recording_1_id": "r1",
                "context_short": "concise context",
                "coach_insight": "already present",
                "report_grade": None,
                "report_comment": "",
            }
            hw.db.get_recording_for_homework_session = lambda *_args, **_kwargs: {
                "id": "r1",
                "storage_path": "",
                "transcription_text": "Student transcript here.",
                "words_per_minute": 122,
                "filler_words_count": {"total": 1, "breakdown": {"um": 1}},
            }
            hw.db.v2_get_performance_history = lambda _uid, limit=5: [
                {"session_id": "s1", "created_at": "2026-04-10T10:00:00Z", "score": 0.73}
            ]
            hw.db.get_sniper_profile_payload = lambda _uid: {"realtime_level": 2, "realtime_step": 3}
            hw.db.get_session_sniper_metrics = lambda _sid: {"wpm": 122, "student_rating_1_10": 4}
            hw.ensure_student_completion_email = lambda *_args, **_kwargs: True
            hw.best_effort_backfill_recording_1_transcript = lambda *_args, **_kwargs: False

            with self.app.test_request_context("/v2/homework/session/s1/report", method="GET"):
                hw.request.user_id = "u1"
                hw.request.token_payload = {}
                response, status = hw.homework_get_report.__wrapped__("s1")

            payload = response.get_json()
            self.assertEqual(status, 200)
            self.assertEqual(payload["score_for_display"], 73)
            self.assertEqual(payload["scores"]["overall"], 73)
        finally:
            hw.db.v2_get_session = original_v2_get_session
            hw.db.get_recording_for_homework_session = original_get_recording_for_homework_session
            hw.db.v2_get_performance_history = original_v2_get_performance_history
            hw.db.get_sniper_profile_payload = original_get_sniper_profile_payload
            hw.db.get_session_sniper_metrics = original_get_session_sniper_metrics
            hw.ensure_student_completion_email = original_ensure_student_completion_email
            hw.best_effort_backfill_recording_1_transcript = original_backfill

    def test_get_report_allows_completed_session_with_missing_transcript(self):
        original_v2_get_session = hw.db.v2_get_session
        original_get_recording_for_homework_session = hw.db.get_recording_for_homework_session
        original_v2_get_performance_history = hw.db.v2_get_performance_history
        original_get_sniper_profile_payload = hw.db.get_sniper_profile_payload
        original_get_session_sniper_metrics = hw.db.get_session_sniper_metrics
        original_ensure_student_completion_email = hw.ensure_student_completion_email
        original_backfill = hw.best_effort_backfill_recording_1_transcript
        try:
            hw.db.v2_get_session = lambda _sid, _uid: {
                "id": "s2",
                "status": hw.STATUS_COMPLETED,
                "context_long": "Fallback report body",
                "report_id": None,
                "score": 0.55,
                "score_for_display": 55,
                "recording_1_id": "r2",
                "context_short": "context present",
                "coach_insight": "insight exists",
                "report_grade": None,
                "report_comment": "",
            }
            hw.db.get_recording_for_homework_session = lambda *_args, **_kwargs: {
                "id": "r2",
                "storage_path": "",
                "transcription_text": "",
                "words_per_minute": 110,
                "filler_words_count": {"total": 0, "breakdown": {}},
            }
            hw.db.v2_get_performance_history = lambda _uid, limit=5: [
                {"session_id": "s2", "created_at": "2026-04-10T10:00:00Z", "score": 0.55}
            ]
            hw.db.get_sniper_profile_payload = lambda _uid: {"realtime_level": 1, "realtime_step": 2}
            hw.db.get_session_sniper_metrics = lambda _sid: {"wpm": 110}
            hw.ensure_student_completion_email = lambda *_args, **_kwargs: True
            hw.best_effort_backfill_recording_1_transcript = lambda *_args, **_kwargs: False

            with self.app.test_request_context("/v2/homework/session/s2/report", method="GET"):
                hw.request.user_id = "u1"
                hw.request.token_payload = {}
                response, status = hw.homework_get_report.__wrapped__("s2")

            payload = response.get_json()
            self.assertEqual(status, 200)
            self.assertEqual(payload.get("report_quality"), "degraded_missing_transcript")
            self.assertFalse(payload.get("transcript_available", True))
            self.assertEqual(payload.get("transcription_text"), "")
        finally:
            hw.db.v2_get_session = original_v2_get_session
            hw.db.get_recording_for_homework_session = original_get_recording_for_homework_session
            hw.db.v2_get_performance_history = original_v2_get_performance_history
            hw.db.get_sniper_profile_payload = original_get_sniper_profile_payload
            hw.db.get_session_sniper_metrics = original_get_session_sniper_metrics
            hw.ensure_student_completion_email = original_ensure_student_completion_email
            hw.best_effort_backfill_recording_1_transcript = original_backfill

    def test_get_report_recovers_transcript_via_backfill(self):
        original_v2_get_session = hw.db.v2_get_session
        original_get_recording_for_homework_session = hw.db.get_recording_for_homework_session
        original_get_recording = hw.db.get_recording
        original_v2_get_performance_history = hw.db.v2_get_performance_history
        original_get_sniper_profile_payload = hw.db.get_sniper_profile_payload
        original_get_session_sniper_metrics = hw.db.get_session_sniper_metrics
        original_ensure_student_completion_email = hw.ensure_student_completion_email
        original_backfill = hw.best_effort_backfill_recording_1_transcript
        try:
            state = {"calls": 0}
            hw.db.v2_get_session = lambda _sid, _uid: {
                "id": "s3",
                "status": hw.STATUS_COMPLETED,
                "context_long": "Fallback report body",
                "report_id": None,
                "score": 0.61,
                "score_for_display": 61,
                "recording_1_id": "r3",
                "context_short": "context present",
                "coach_insight": "insight exists",
                "report_grade": None,
                "report_comment": "",
            }

            def _recording_for_session(*_args, **_kwargs):
                state["calls"] += 1
                if state["calls"] == 1:
                    return {
                        "id": "r3",
                        "storage_path": "",
                        "transcription_text": "",
                        "words_per_minute": 108,
                        "filler_words_count": {"total": 0, "breakdown": {}},
                    }
                return {
                    "id": "r3",
                    "storage_path": "",
                    "transcription_text": "Recovered transcript.",
                    "words_per_minute": 109,
                    "filler_words_count": {"total": 1, "breakdown": {"um": 1}},
                }

            hw.db.get_recording_for_homework_session = _recording_for_session
            hw.db.get_recording = lambda *_args, **_kwargs: None
            hw.db.v2_get_performance_history = lambda _uid, limit=5: [
                {"session_id": "s3", "created_at": "2026-04-10T10:00:00Z", "score": 0.61}
            ]
            hw.db.get_sniper_profile_payload = lambda _uid: {"realtime_level": 1, "realtime_step": 2}
            hw.db.get_session_sniper_metrics = lambda _sid: {"wpm": 109}
            hw.ensure_student_completion_email = lambda *_args, **_kwargs: True
            hw.best_effort_backfill_recording_1_transcript = lambda *_args, **_kwargs: True

            with self.app.test_request_context("/v2/homework/session/s3/report", method="GET"):
                hw.request.user_id = "u1"
                hw.request.token_payload = {}
                response, status = hw.homework_get_report.__wrapped__("s3")

            payload = response.get_json()
            self.assertEqual(status, 200)
            self.assertEqual(payload.get("transcription_text"), "Recovered transcript.")
            self.assertNotEqual(payload.get("report_quality"), "degraded_missing_transcript")
        finally:
            hw.db.v2_get_session = original_v2_get_session
            hw.db.get_recording_for_homework_session = original_get_recording_for_homework_session
            hw.db.get_recording = original_get_recording
            hw.db.v2_get_performance_history = original_v2_get_performance_history
            hw.db.get_sniper_profile_payload = original_get_sniper_profile_payload
            hw.db.get_session_sniper_metrics = original_get_session_sniper_metrics
            hw.ensure_student_completion_email = original_ensure_student_completion_email
            hw.best_effort_backfill_recording_1_transcript = original_backfill


@unittest.skipIf(_DB_IMPORT_ERROR is not None, f"db tests require full app deps: {_DB_IMPORT_ERROR}")
class SessionSniperRatingUpsertTests(unittest.TestCase):
    def test_upsert_preserves_existing_metric_fields(self):
        dbs = db_module.db
        original_v2_get_session = dbs.v2_get_session
        original_get_session_sniper_metrics = dbs.get_session_sniper_metrics
        original_client = dbs.client
        try:
            captured = {"payload": None, "on_conflict": None}

            class _FakeTable:
                def upsert(self, payload, on_conflict=None):
                    captured["payload"] = dict(payload)
                    captured["on_conflict"] = on_conflict
                    return self

                def execute(self):
                    return {"ok": True}

            class _FakeClient:
                def table(self, _name):
                    return _FakeTable()

            dbs.v2_get_session = lambda _sid, _uid: {"id": "s1", "user_id": "u1"}
            dbs.get_session_sniper_metrics = lambda _sid: {
                "wpm": 121.0,
                "pause_ms": 430.0,
                "dynamic_db": 17.2,
                "energy_ratio": 0.74,
                "stage_score": 0.68,
                "recording_id": "r1",
            }
            dbs.client = _FakeClient()

            ok = dbs.update_or_set_session_sniper_rating("s1", "u1", 5)
            self.assertTrue(ok)
            self.assertEqual(captured["on_conflict"], "session_id")
            self.assertEqual(captured["payload"]["student_rating_1_10"], 5)
            self.assertEqual(captured["payload"]["stage_score"], 0.68)
            self.assertEqual(captured["payload"]["dynamic_db"], 17.2)
            self.assertEqual(captured["payload"]["recording_id"], "r1")
        finally:
            dbs.v2_get_session = original_v2_get_session
            dbs.get_session_sniper_metrics = original_get_session_sniper_metrics
            dbs.client = original_client


if __name__ == "__main__":
    unittest.main()
