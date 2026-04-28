"""Admin recommendation-engine calibration: upload mp3 and run the full recording-1 pipeline.

Covers POST /v2/admin/students/<user_id>/sessions/upload-recording.
"""
import io
import unittest

try:
    from flask import Flask
    from werkzeug.datastructures import FileStorage
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    FileStorage = None
    v2 = None
    _IMPORT_ERROR = import_err


VALID_USER_ID = "11111111-1111-4111-8111-111111111111"


@unittest.skipIf(_IMPORT_ERROR is not None, f"admin upload-recording tests require full app deps: {_IMPORT_ERROR}")
class AdminUploadRecordingTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.admin_id = "admin-1"

        self.created_session = {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "user_id": VALID_USER_ID,
            "status": "task",
        }
        self.session_updates: list[dict] = []
        self.uploads: list[dict] = []
        self.recordings: list[dict] = []
        self.enqueued_jobs: list[dict] = []
        self.assigned_task = {"id": "task-1", "text": "Read this aloud."}
        self.originals = {}

        self._patch("is_admin", lambda _uid: True)
        self._patch_db("v2_ensure_default_student_task", lambda _uid: True)
        self._patch_db("v2_get_assigned_task_for_user", lambda _uid: dict(self.assigned_task) if self.assigned_task else None)
        self._patch_db("v2_create_homework_session", self._fake_create_session)
        self._patch_db("upload_audio", self._fake_upload_audio)
        self._patch_db("create_recording", self._fake_create_recording)
        self._patch_db("v2_update_session", self._fake_update_session)
        self._patch_module("recording_1_job", "enqueue_recording_1_job", self._fake_enqueue_job)

    def tearDown(self):
        for target, attr, original in reversed(self.originals.values()):
            setattr(target, attr, original)

    def _patch(self, attr, replacement):
        key = f"module:{attr}"
        self.originals[key] = (v2, attr, getattr(v2, attr))
        setattr(v2, attr, replacement)

    def _patch_db(self, attr, replacement):
        key = f"db:{attr}"
        self.originals[key] = (v2.db, attr, getattr(v2.db, attr))
        setattr(v2.db, attr, replacement)

    def _patch_module(self, module_name, attr, replacement):
        from importlib import import_module
        mod = import_module(f"services.{module_name}")
        key = f"services.{module_name}:{attr}"
        self.originals[key] = (mod, attr, getattr(mod, attr))
        setattr(mod, attr, replacement)

    def _fake_create_session(self, user_id):
        self.created_session["user_id"] = user_id
        return dict(self.created_session)

    def _fake_upload_audio(self, bucket, path, data, content_type=None):
        self.uploads.append({"bucket": bucket, "path": path, "size": len(data), "content_type": content_type})
        return True

    def _fake_create_recording(self, payload):
        row = dict(payload)
        row["id"] = "rec-" + str(len(self.recordings) + 1)
        self.recordings.append(row)
        return row

    def _fake_update_session(self, session_id, user_id, data):
        self.session_updates.append({"session_id": session_id, "user_id": user_id, "data": dict(data or {})})
        return {"id": session_id, "user_id": user_id, **(data or {})}

    def _fake_enqueue_job(self, session_id, recording_id, storage_path, user_id, duration_seconds=None, **kwargs):
        self.enqueued_jobs.append({
            "session_id": session_id,
            "recording_id": recording_id,
            "storage_path": storage_path,
            "user_id": user_id,
            "duration_seconds": duration_seconds,
        })

    def _build_audio_file(self, *, filename="speech.mp3", content=b"FAKE_MP3_BYTES", mimetype="audio/mpeg"):
        return FileStorage(stream=io.BytesIO(content), filename=filename, content_type=mimetype)

    def _invoke(self, *, user_id=VALID_USER_ID, audio_file=None, form=None):
        files = {"audio_file": audio_file} if audio_file is not None else {}
        with self.app.test_request_context(
            f"/v2/admin/students/{user_id}/sessions/upload-recording",
            method="POST",
            data={**(form or {}), **files},
            content_type="multipart/form-data",
        ):
            v2.request.user_id = self.admin_id
            response, status = v2.v2_admin_upload_session_recording.__wrapped__(user_id)
            return status, response.get_json()

    def test_happy_path_creates_session_recording_uploads_and_enqueues(self):
        audio = self._build_audio_file()
        status, payload = self._invoke(audio_file=audio)

        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["session_id"], self.created_session["id"])
        self.assertTrue(payload["recording_id"].startswith("rec-"))
        self.assertIn(self.created_session["id"], payload["storage_path"])
        self.assertTrue(payload["storage_path"].endswith(".mp3"))

        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(self.uploads[0]["size"], len(b"FAKE_MP3_BYTES"))

        self.assertEqual(len(self.recordings), 1)
        rec = self.recordings[0]
        self.assertEqual(rec["user_id"], VALID_USER_ID)
        self.assertEqual(rec["session_v2_id"], self.created_session["id"])
        self.assertEqual(rec["recording_origin"], "admin_upload")

        self.assertEqual(len(self.enqueued_jobs), 1)
        job = self.enqueued_jobs[0]
        self.assertEqual(job["session_id"], self.created_session["id"])
        self.assertEqual(job["recording_id"], rec["id"])
        self.assertEqual(job["user_id"], VALID_USER_ID)

        self.assertEqual(len(self.session_updates), 1)
        update = self.session_updates[0]["data"]
        self.assertEqual(update["recording_1_id"], rec["id"])
        self.assertEqual(update["status"], "completing_from_recording_1")
        self.assertEqual(update["recording_1_processing_status"], "pending")
        self.assertIsNotNone(update["self_rating_submitted_at"])
        self.assertEqual(update["session_task_id"], "task-1")
        self.assertEqual(update["session_task_text"], "Read this aloud.")

    def test_falls_back_to_placeholder_task_when_no_assignment(self):
        self.assigned_task = None
        audio = self._build_audio_file()
        status, payload = self._invoke(audio_file=audio)

        self.assertEqual(status, 201)
        update = self.session_updates[0]["data"]
        self.assertIsNone(update["session_task_id"])
        self.assertIn("calibration", update["session_task_text"].lower())

    def test_rejects_invalid_user_id(self):
        audio = self._build_audio_file()
        status, payload = self._invoke(user_id="not-a-uuid", audio_file=audio)
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.enqueued_jobs, [])

    def test_rejects_missing_audio_file(self):
        status, payload = self._invoke(audio_file=None)
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "AUDIO_FILE_REQUIRED")

    def test_rejects_unsupported_extension(self):
        audio = self._build_audio_file(filename="speech.txt", mimetype="text/plain")
        status, payload = self._invoke(audio_file=audio)
        self.assertEqual(status, 415)
        self.assertEqual(payload["code"], "UNSUPPORTED_AUDIO_FORMAT")
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.enqueued_jobs, [])

    def test_rejects_empty_file(self):
        audio = self._build_audio_file(content=b"")
        status, payload = self._invoke(audio_file=audio)
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_MULTIPART")
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.enqueued_jobs, [])

    def test_storage_failure_returns_500_and_does_not_enqueue(self):
        def boom(*_a, **_kw):
            raise RuntimeError("supabase storage down")
        self._patch_db("upload_audio", boom)
        audio = self._build_audio_file()
        status, payload = self._invoke(audio_file=audio)
        self.assertEqual(status, 500)
        self.assertEqual(payload["code"], "UPLOAD_FAILED")
        self.assertEqual(self.recordings, [])
        self.assertEqual(self.enqueued_jobs, [])

    def test_create_recording_pgrst204_falls_back_without_recording_origin(self):
        calls = {"n": 0}

        def flaky_create(payload):
            calls["n"] += 1
            if calls["n"] == 1 and "recording_origin" in payload:
                raise RuntimeError("PGRST204: column recording_origin missing")
            row = dict(payload)
            row["id"] = "rec-fallback"
            self.recordings.append(row)
            return row
        self._patch_db("create_recording", flaky_create)

        audio = self._build_audio_file()
        status, payload = self._invoke(audio_file=audio)

        self.assertEqual(status, 201)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(payload["recording_id"], "rec-fallback")
        self.assertNotIn("recording_origin", self.recordings[0])

    def test_passes_optional_duration_seconds(self):
        audio = self._build_audio_file()
        status, payload = self._invoke(audio_file=audio, form={"duration_seconds": "42.5"})
        self.assertEqual(status, 201)
        self.assertEqual(self.enqueued_jobs[0]["duration_seconds"], 42.5)
        self.assertEqual(self.recordings[0].get("duration_seconds"), 42.5)


if __name__ == "__main__":
    unittest.main()
