import unittest
import copy

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
        self.overrides = {
            self.student_a: {"user_id": self.student_a, "assigned_task_id": "task-a-before"},
            self.student_b: {"user_id": self.student_b, "assigned_task_id": "task-b-before"},
        }
        self.drafts = {
            self.student_a: {
                "id": "draft-a",
                "user_id": self.student_a,
                "status": "pending",
                "draft_payload": {
                    "task_draft": "task A before",
                    "script_draft": "script A before",
                    "video_script": "script A before",
                },
                "master_task_text": "task A before",
                "ai_draft_video_script": "script A ai",
            },
            self.student_b: {
                "id": "draft-b",
                "user_id": self.student_b,
                "status": "pending",
                "draft_payload": {
                    "task_draft": "task B before",
                    "script_draft": "script B before",
                    "video_script": "script B before",
                },
                "master_task_text": "task B before",
                "ai_draft_video_script": "script B ai",
            },
        }
        self.originals = {}
        self._patch("is_admin", lambda _uid: True)
        self._patch("_pick_student_draft", self._fake_pick_student_draft)
        self._patch_db("v2_upsert_speaker_profile", self._fake_upsert_speaker_profile)
        self._patch_db("v2_get_speaker_profile", self._fake_get_speaker_profile)
        self._patch_db("get_user_email_from_auth", lambda uid: f"{uid}@example.com")
        self._patch_db("v2_get_student_details", lambda _uid: {})
        self._patch_db("v2_get_student_overrides", self._fake_get_student_overrides)
        self._patch_db("v2_upsert_student_overrides", self._fake_upsert_student_overrides)
        self._patch_db("get_sniper_profile_payload", lambda _uid: {"realtime_level": None, "realtime_step": None})
        self._patch_db("v2_get_student_coaching_memory", lambda _uid: None)
        self._patch_db("v2_get_student_tasks", lambda _uid: [])
        self._patch_db("v2_get_last_report_for_user", lambda _uid: None)
        self._patch_db("v2_get_sessions_with_previews", lambda _uid, limit=50: [])
        self._patch_db("v2_get_admin_measured_metrics_snapshot", lambda _uid: {"wpm_high": False})
        self._patch_db("get_similar_students_by_wpm", lambda _uid: [])
        self._patch_db("create_admin_annotation_event", lambda **_kwargs: True)
        self._patch_db("get_admin_student_send_draft", self._fake_get_admin_student_send_draft)
        self._patch_db("insert_admin_student_send_drafts", lambda rows: rows)
        self._patch_db("list_admin_student_send_drafts", lambda **_kwargs: [])
        self._patch_db("get_user_name_from_auth", lambda _uid: "Student")
        self._patch_db("get_sniper_profile", lambda _uid: {})
        self._patch_db("v2_get_last_completed_session_full", lambda _uid: None)
        self._patch_db("v2_get_last_completed_sessions", lambda _uid, limit=4: [])
        self._patch_db("v2_get_student_feedback_drafts", lambda _uid, limit=4: [])
        self._patch_db("client", self._FakeClient(self))

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

    def _fake_get_student_overrides(self, user_id):
        row = self.overrides.get(user_id)
        return dict(row) if row else None

    def _fake_upsert_student_overrides(self, user_id, data):
        existing = dict(self.overrides.get(user_id) or {"user_id": user_id})
        for key, value in data.items():
            existing[key] = value
        self.overrides[user_id] = existing
        return dict(existing)

    def _fake_pick_student_draft(self, user_id, session_id=None, draft_id=None, include_sent=False):
        row = self.drafts.get(user_id)
        if not row:
            return None
        if draft_id and str(row.get("id")) != str(draft_id):
            return None
        return copy.deepcopy(row)

    def _fake_get_admin_student_send_draft(self, draft_id, user_id):
        row = self.drafts.get(user_id)
        if not row:
            return None
        if str(row.get("id")) != str(draft_id):
            return None
        return copy.deepcopy(row)

    class _FakeClient:
        def __init__(self, outer):
            self.outer = outer

        def table(self, table_name):
            return AdminStudentProfileRegressionsTests._FakeTable(self.outer, table_name)

    class _FakeTable:
        def __init__(self, outer, table_name):
            self.outer = outer
            self.table_name = table_name
            self._update_payload = None
            self._filters = {}

        def update(self, payload):
            self._update_payload = dict(payload)
            return self

        def eq(self, key, value):
            self._filters[key] = value
            return self

        def execute(self):
            class _Result:
                def __init__(self, data):
                    self.data = data

            if self.table_name != "admin_student_send_drafts" or self._update_payload is None:
                return _Result([])
            user_id = self._filters.get("user_id")
            draft_id = self._filters.get("id")
            row = self.outer.drafts.get(user_id)
            if not row or str(row.get("id")) != str(draft_id):
                return _Result([])
            updated_row = copy.deepcopy(row)
            for key, value in self._update_payload.items():
                updated_row[key] = copy.deepcopy(value)
            self.outer.drafts[user_id] = updated_row
            return _Result([copy.deepcopy(updated_row)])

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

    def test_overrides_update_isolation_and_freshness(self):
        with self.app.test_request_context(
            f"/v2/admin/students/{self.student_a}/overrides",
            method="PUT",
            json={"assigned_task_id": "task-a-after"},
        ):
            response, status = v2.v2_admin_student_overrides.__wrapped__(self.student_a)
            payload = response.get_json()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["user_id"], self.student_a)
        self.assertEqual((payload.get("overrides") or {}).get("user_id"), self.student_a)
        self.assertEqual((payload.get("overrides") or {}).get("assigned_task_id"), "task-a-after")
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(self.overrides[self.student_b]["assigned_task_id"], "task-b-before")

    def test_task_and_video_script_draft_update_isolation_and_freshness(self):
        with self.app.test_request_context(
            f"/v2/admin/students/{self.student_a}/drafts",
            method="PUT",
            json={"task_draft": "task A after", "script_draft": "script A after"},
        ):
            v2.request.user_id = self.admin_id
            response, status = v2.v2_admin_copilot_student_drafts.__wrapped__(self.student_a)
            payload = response.get_json()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["user_id"], self.student_a)
        draft = payload.get("draft") or {}
        self.assertEqual(draft.get("user_id"), self.student_a)
        self.assertEqual(draft.get("task_draft"), "task A after")
        self.assertEqual(draft.get("script_draft"), "script A after")
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        self.assertEqual(self.drafts[self.student_b]["draft_payload"]["task_draft"], "task B before")
        self.assertEqual(self.drafts[self.student_b]["draft_payload"]["script_draft"], "script B before")


if __name__ == "__main__":
    unittest.main()
