import unittest

try:
    from flask import Flask
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    v2 = None
    _IMPORT_ERROR = import_err


@unittest.skipIf(_IMPORT_ERROR is not None, f"v2 admin tests require full app deps: {_IMPORT_ERROR}")
class AdminStudentProfileRegressionsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.student_a = "student-a"
        self.student_b = "student-b"
        self.admin_id = "admin-1"
        self.profiles = {
            self.student_a: {"user_id": self.student_a, "coach_notes": "A before"},
            self.student_b: {"user_id": self.student_b, "coach_notes": "B before"},
        }
        self.originals = {}
        self._patch("is_admin", lambda _uid: True)
        self._patch("_pick_student_draft", lambda *_args, **_kwargs: None)
        self._patch_db("v2_upsert_speaker_profile", self._fake_upsert_speaker_profile)
        self._patch_db("v2_get_speaker_profile", self._fake_get_speaker_profile)
        self._patch_db("get_user_email_from_auth", lambda uid: f"{uid}@example.com")
        self._patch_db("v2_get_student_details", lambda _uid: {})
        self._patch_db("v2_get_student_overrides", lambda _uid: {})
        self._patch_db("get_sniper_profile_payload", lambda _uid: {"realtime_level": None, "realtime_step": None})
        self._patch_db("v2_get_student_coaching_memory", lambda _uid: None)
        self._patch_db("v2_get_student_tasks", lambda _uid: [])
        self._patch_db("v2_get_last_report_for_user", lambda _uid: None)
        self._patch_db("v2_get_sessions_with_previews", lambda _uid, limit=50: [])
        self._patch_db("v2_get_admin_measured_metrics_snapshot", lambda _uid: {"wpm_high": False})
        self._patch_db("get_similar_students_by_wpm", lambda _uid: [])

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

    def _fake_get_speaker_profile(self, user_id):
        row = self.profiles.get(user_id)
        return dict(row) if row else None

    def _fake_upsert_speaker_profile(self, user_id, data):
        existing = dict(self.profiles.get(user_id) or {"user_id": user_id})
        if "coach_notes" in data:
            existing["coach_notes"] = data.get("coach_notes")
        self.profiles[user_id] = existing
        return dict(existing)

    def test_speaker_profile_update_read_isolation_and_freshness(self):
        with self.app.test_request_context(
            f"/v2/admin/students/{self.student_a}/speaker-profile",
            method="PUT",
            json={"coach_notes": "A after"},
        ):
            response, status = v2.v2_admin_student_speaker_profile.__wrapped__(self.student_a)
            put_payload = response.get_json()

        self.assertEqual(status, 200)
        self.assertEqual(put_payload["status"], "ok")
        self.assertEqual(put_payload["user_id"], self.student_a)
        self.assertEqual(put_payload["speaker_profile"]["user_id"], self.student_a)
        self.assertEqual(put_payload["speaker_profile"]["coach_notes"], "A after")
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

        with self.app.test_request_context(f"/v2/admin/students/{self.student_a}", method="GET"):
            v2.request.user_id = self.admin_id
            response_a, status_a = v2.v2_admin_student_profile.__wrapped__(self.student_a)
            payload_a = response_a.get_json()

        with self.app.test_request_context(f"/v2/admin/students/{self.student_b}", method="GET"):
            v2.request.user_id = self.admin_id
            response_b, status_b = v2.v2_admin_student_profile.__wrapped__(self.student_b)
            payload_b = response_b.get_json()

        self.assertEqual(status_a, 200)
        self.assertEqual(payload_a["user_id"], self.student_a)
        self.assertEqual((payload_a.get("speaker_profile") or {}).get("user_id"), self.student_a)
        self.assertEqual((payload_a.get("speaker_profile") or {}).get("coach_notes"), "A after")
        self.assertIn("no-store", response_a.headers.get("Cache-Control", ""))

        self.assertEqual(status_b, 200)
        self.assertEqual(payload_b["user_id"], self.student_b)
        self.assertEqual((payload_b.get("speaker_profile") or {}).get("user_id"), self.student_b)
        self.assertEqual((payload_b.get("speaker_profile") or {}).get("coach_notes"), "B before")
        self.assertIn("no-store", response_b.headers.get("Cache-Control", ""))


if __name__ == "__main__":
    unittest.main()
