"""Curiosity Gate funnel: anonymous upload + post-auth claim.

Covers:
  POST /v2/public/shaky-voice/upload  — no-auth, rate-limited
  POST /v2/public/shaky-voice/claim   — auth required, idempotent

Critical invariants:
  * Anonymous upload does NOT enqueue paid pipeline.
  * Claim enqueues the pipeline exactly once per session.
  * Idempotency: re-claim by same user → 200; claim by other user → 409.
  * Rate limiting blocks at the per-IP cap.
"""
import io
import unittest
from unittest.mock import patch

try:
    from flask import Flask
    from werkzeug.datastructures import FileStorage
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover
    Flask = None
    FileStorage = None
    v2 = None
    _IMPORT_ERROR = import_err


VALID_GUEST_SESSION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@unittest.skipIf(_IMPORT_ERROR is not None, f"guest funnel tests require full app deps: {_IMPORT_ERROR}")
class GuestFunnelUploadTests(unittest.TestCase):
    """POST /v2/public/shaky-voice/upload."""

    def setUp(self):
        self.app = Flask(__name__)
        self.recordings = []
        self.guest_sessions = []
        self.uploads = []
        self.originals = {}

        # Reset rate limiter between tests so they don't pollute each other.
        v2._guest_funnel_rate_limit.clear()

        self._set_config("GUEST_FUNNEL_ENABLED", True)
        self._set_config("GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR", 5)
        self._set_config("GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR", 200)
        self._set_config("GUEST_FUNNEL_MAX_AUDIO_SIZE_MB", 5)

        self._patch_db("upload_audio", self._fake_upload_audio)
        self._patch_db("create_recording", self._fake_create_recording)
        self._patch_db("v2_create_guest_session", self._fake_create_guest_session)

    def tearDown(self):
        for target, attr, original in reversed(self.originals.values()):
            setattr(target, attr, original)
        v2._guest_funnel_rate_limit.clear()

    def _set_config(self, attr, value):
        key = f"config:{attr}"
        self.originals[key] = (v2.config, attr, getattr(v2.config, attr, None))
        setattr(v2.config, attr, value)

    def _patch_db(self, attr, replacement):
        key = f"db:{attr}"
        self.originals[key] = (v2.db, attr, getattr(v2.db, attr))
        setattr(v2.db, attr, replacement)

    def _fake_upload_audio(self, bucket, path, data, content_type=None):
        self.uploads.append({"bucket": bucket, "path": path, "size": len(data)})
        return True

    def _fake_create_recording(self, payload):
        row = dict(payload)
        if "id" not in row:
            row["id"] = f"rec-{len(self.recordings) + 1}"
        self.recordings.append(row)
        return row

    def _fake_create_guest_session(self, guest_session_id, *, recording_id):
        row = {
            "id": guest_session_id,
            "user_id": None,
            "status": "guest_pending_claim",
            "recording_1_id": recording_id,
        }
        self.guest_sessions.append(row)
        return dict(row)

    def _build_audio(self, *, filename="trial.mp3", content=b"FAKE_15_SEC_MP3", mimetype="audio/mpeg"):
        return FileStorage(stream=io.BytesIO(content), filename=filename, content_type=mimetype)

    def _invoke(self, *, audio_file=None, ip="1.2.3.4", form=None):
        files = {"audio_file": audio_file} if audio_file is not None else {}
        with self.app.test_request_context(
            "/v2/public/shaky-voice/upload",
            method="POST",
            data={**(form or {}), **files},
            content_type="multipart/form-data",
            headers={"X-Forwarded-For": ip},
        ):
            response, status = v2.v2_public_shaky_voice_upload()
            return status, response.get_json()

    def test_happy_path_creates_session_and_recording_without_enqueueing_pipeline(self):
        # Patch enqueue to assert it is NEVER called on upload (critical
        # cost-control invariant).
        with patch("services.recording_1_job.enqueue_recording_1_job") as enqueue_mock:
            status, payload = self._invoke(audio_file=self._build_audio())
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "ok")
        # UUID format
        self.assertEqual(len(payload["guest_session_id"]), 36)

        self.assertEqual(len(self.uploads), 1)
        self.assertTrue(self.uploads[0]["path"].startswith("guest_funnel/"))
        self.assertEqual(len(self.recordings), 1)
        rec = self.recordings[0]
        self.assertIsNone(rec["user_id"])
        self.assertEqual(rec["session_v2_id"], payload["guest_session_id"])
        self.assertEqual(rec["recording_origin"], "guest_funnel")
        self.assertEqual(len(self.guest_sessions), 1)
        self.assertEqual(self.guest_sessions[0]["id"], payload["guest_session_id"])
        self.assertIsNone(self.guest_sessions[0]["user_id"])

        # Pipeline must NOT have been enqueued.
        enqueue_mock.assert_not_called()

    def test_disabled_returns_503(self):
        self._set_config("GUEST_FUNNEL_ENABLED", False)
        status, payload = self._invoke(audio_file=self._build_audio())
        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "GUEST_FUNNEL_DISABLED")
        self.assertEqual(self.uploads, [])

    def test_missing_audio_file_returns_400(self):
        status, payload = self._invoke(audio_file=None)
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "AUDIO_FILE_REQUIRED")

    def test_unsupported_extension_returns_415(self):
        bad = self._build_audio(filename="trial.txt", mimetype="text/plain")
        status, payload = self._invoke(audio_file=bad)
        self.assertEqual(status, 415)
        self.assertEqual(payload["code"], "UNSUPPORTED_AUDIO_FORMAT")

    def test_empty_file_returns_400(self):
        empty = self._build_audio(content=b"")
        status, payload = self._invoke(audio_file=empty)
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_MULTIPART")

    def test_oversized_file_returns_413(self):
        self._set_config("GUEST_FUNNEL_MAX_AUDIO_SIZE_MB", 0)  # any non-empty payload exceeds 0 MB
        big = self._build_audio(content=b"X" * 1024)
        status, payload = self._invoke(audio_file=big)
        self.assertEqual(status, 413)
        self.assertEqual(payload["code"], "FILE_TOO_LARGE")
        self.assertEqual(self.uploads, [])

    def test_per_ip_rate_limit_returns_429(self):
        self._set_config("GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR", 1)
        # First call succeeds.
        status1, _ = self._invoke(audio_file=self._build_audio(), ip="9.9.9.9")
        self.assertEqual(status1, 201)
        # Second call from the same IP is blocked.
        status2, payload2 = self._invoke(audio_file=self._build_audio(), ip="9.9.9.9")
        self.assertEqual(status2, 429)
        self.assertEqual(payload2["code"], "RATE_LIMITED")
        # A different IP should still be allowed.
        status3, _ = self._invoke(audio_file=self._build_audio(), ip="9.9.9.8")
        self.assertEqual(status3, 201)


@unittest.skipIf(_IMPORT_ERROR is not None, f"guest funnel tests require full app deps: {_IMPORT_ERROR}")
class GuestFunnelClaimTests(unittest.TestCase):
    """POST /v2/public/shaky-voice/claim."""

    def setUp(self):
        self.app = Flask(__name__)
        self.user_id = "11111111-1111-4111-8111-111111111111"
        self.guest_session_id = VALID_GUEST_SESSION_ID
        self.session_row = {
            "id": self.guest_session_id,
            "user_id": None,
            "status": "guest_pending_claim",
            "recording_1_id": "rec-funnel-1",
            "created_at": "2026-04-30T10:00:00+00:00",
        }
        self.recording_row = {
            "id": "rec-funnel-1",
            "user_id": None,
            "session_v2_id": self.guest_session_id,
            "storage_path": f"guest_funnel/{self.guest_session_id}/audio.mp3",
            "duration_seconds": 14.5,
        }
        self.enqueued_jobs = []
        self.originals = {}

        self._set_config("GUEST_FUNNEL_ENABLED", True)
        self._set_config("GUEST_FUNNEL_TTL_HOURS", 24)

        self._patch_db("v2_get_session_by_id", self._fake_get_session_by_id)
        self._patch_db("v2_claim_guest_session", self._fake_claim)
        self._patch_db("get_recording", self._fake_get_recording)
        self._patch_module("recording_1_job", "enqueue_recording_1_job", self._fake_enqueue)

    def tearDown(self):
        for target, attr, original in reversed(self.originals.values()):
            setattr(target, attr, original)

    def _set_config(self, attr, value):
        key = f"config:{attr}"
        self.originals[key] = (v2.config, attr, getattr(v2.config, attr, None))
        setattr(v2.config, attr, value)

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

    def _fake_get_session_by_id(self, session_id):
        if session_id == self.session_row["id"]:
            return dict(self.session_row)
        return None

    def _fake_claim(self, session_id, user_id):
        if session_id != self.session_row["id"]:
            return None
        if self.session_row.get("user_id"):
            # already claimed (race-loss simulation)
            return None
        # Mutate the in-memory row to simulate the atomic update.
        self.session_row["user_id"] = user_id
        self.session_row["guest_claimed_at"] = "2026-04-30T11:00:00+00:00"
        self.session_row["status"] = "completing_from_recording_1"
        return dict(self.session_row)

    def _fake_get_recording(self, recording_id, user_id):
        if recording_id == self.recording_row["id"]:
            return dict(self.recording_row)
        return None

    def _fake_enqueue(self, session_id, recording_id, storage_path, user_id, duration_seconds=None, **kwargs):
        self.enqueued_jobs.append({
            "session_id": session_id,
            "recording_id": recording_id,
            "user_id": user_id,
            "storage_path": storage_path,
            "duration_seconds": duration_seconds,
        })

    def _invoke(self, *, body=None, user_id=None):
        with self.app.test_request_context(
            "/v2/public/shaky-voice/claim",
            method="POST",
            json=body if body is not None else {"guest_session_id": self.guest_session_id},
        ):
            v2.request.user_id = user_id or self.user_id
            response, status = v2.v2_public_shaky_voice_claim.__wrapped__()
            return status, response.get_json()

    def test_happy_path_binds_user_and_enqueues_pipeline(self):
        status, payload = self._invoke()
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["session_id"], self.guest_session_id)
        self.assertEqual(payload["analysis_status"], "queued")

        self.assertEqual(self.session_row["user_id"], self.user_id)
        self.assertEqual(self.session_row["status"], "completing_from_recording_1")

        self.assertEqual(len(self.enqueued_jobs), 1)
        job = self.enqueued_jobs[0]
        self.assertEqual(job["session_id"], self.guest_session_id)
        self.assertEqual(job["user_id"], self.user_id)
        self.assertEqual(job["storage_path"], self.recording_row["storage_path"])

    def test_disabled_returns_503(self):
        self._set_config("GUEST_FUNNEL_ENABLED", False)
        status, payload = self._invoke()
        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "GUEST_FUNNEL_DISABLED")

    def test_invalid_uuid_returns_400(self):
        status, payload = self._invoke(body={"guest_session_id": "not-a-uuid"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")

    def test_unknown_session_returns_404(self):
        status, payload = self._invoke(body={"guest_session_id": "ffffffff-ffff-4fff-8fff-ffffffffffff"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "GUEST_SESSION_NOT_FOUND")
        self.assertEqual(self.enqueued_jobs, [])

    def test_already_claimed_by_same_user_is_idempotent(self):
        # Pre-bind to the same user; second claim is a no-op.
        self.session_row["user_id"] = self.user_id
        self.session_row["guest_claimed_at"] = "2026-04-30T10:30:00+00:00"
        status, payload = self._invoke()
        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_status"], "already_claimed")
        # No second pipeline enqueue.
        self.assertEqual(self.enqueued_jobs, [])

    def test_already_claimed_by_other_user_returns_409(self):
        self.session_row["user_id"] = "22222222-2222-4222-8222-222222222222"
        status, payload = self._invoke()
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "ALREADY_CLAIMED")
        self.assertEqual(self.enqueued_jobs, [])

    def test_expired_session_returns_410(self):
        # 25 hours ago > 24h TTL.
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.session_row["created_at"] = old
        status, payload = self._invoke()
        self.assertEqual(status, 410)
        self.assertEqual(payload["code"], "GUEST_SESSION_EXPIRED")
        self.assertEqual(self.enqueued_jobs, [])

    def test_claim_race_loss_returns_409(self):
        # Simulate the row being claimed between probe and atomic update by
        # making v2_claim_guest_session return None with a row that has been
        # bound to a different user in the meantime.
        original_claim = v2.db.v2_claim_guest_session

        def race_lose(session_id, user_id):
            self.session_row["user_id"] = "33333333-3333-4333-8333-333333333333"
            return None
        v2.db.v2_claim_guest_session = race_lose
        try:
            status, payload = self._invoke()
        finally:
            v2.db.v2_claim_guest_session = original_claim
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "ALREADY_CLAIMED")
        self.assertEqual(self.enqueued_jobs, [])


if __name__ == "__main__":
    unittest.main()
