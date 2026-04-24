"""Phase 4: coach approval / override flow on the session PATCH endpoint.

Covers the new `coach_approved_profile` + `coach_approved_task_id` fields on
PATCH /v2/admin/students/<user_id>/sessions/<session_id>, plus the
`admin_annotation_events` rows that land for RLHF training.
"""
import unittest

try:
    from flask import Flask
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    v2 = None
    _IMPORT_ERROR = import_err


AI_PROFILE = "The Overwhelmed"
AI_TASK_ID = "11111111-1111-4111-8111-111111111111"
OTHER_PROFILE = "The Master"
OTHER_TASK_ID = "22222222-2222-4222-8222-222222222222"
STRESSOR_TASK_ID = "33333333-3333-4333-8333-333333333333"
LEGACY_TASK_ID = "44444444-4444-4444-8444-444444444444"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach approval tests require full app deps: {_IMPORT_ERROR}")
class CoachApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.admin_id = "admin-1"
        self.user_id = "student-1"
        self.session_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

        self.sessions = {
            self.session_id: {
                "id": self.session_id,
                "user_id": self.user_id,
                "ai_suggested_profile": AI_PROFILE,
                "ai_suggested_task_id": AI_TASK_ID,
                "coach_approved_profile": None,
                "coach_approved_task_id": None,
                "coach_approved_at": None,
                "report_grade": None,
                "report_comment": None,
            },
        }
        self.tasks_pool = {
            AI_TASK_ID: {"id": AI_TASK_ID, "target_profile": AI_PROFILE, "is_behavioral": True},
            OTHER_TASK_ID: {"id": OTHER_TASK_ID, "target_profile": OTHER_PROFILE, "is_behavioral": True},
            STRESSOR_TASK_ID: {"id": STRESSOR_TASK_ID, "target_profile": "The Stressor", "is_behavioral": True},
            LEGACY_TASK_ID: {"id": LEGACY_TASK_ID, "target_profile": AI_PROFILE, "is_behavioral": False},
        }
        self.annotation_events = []
        self.originals = {}

        self._patch("is_admin", lambda _uid: True)
        self._patch_db("v2_get_session", self._fake_get_session)
        self._patch_db("v2_update_session", self._fake_update_session)
        self._patch_db("v2_get_task_pool_by_id", self._fake_get_task_pool_by_id)
        self._patch_db("create_admin_annotation_event", self._fake_create_annotation_event)

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

    def _fake_get_session(self, session_id, user_id):
        row = self.sessions.get(session_id)
        if not row or row.get("user_id") != user_id:
            return None
        return dict(row)

    def _fake_update_session(self, session_id, user_id, data):
        row = self.sessions.get(session_id)
        if not row or row.get("user_id") != user_id:
            return None
        for key, value in (data or {}).items():
            row[key] = value
        return dict(row)

    def _fake_get_task_pool_by_id(self, task_id):
        row = self.tasks_pool.get(task_id)
        return dict(row) if row else None

    def _fake_create_annotation_event(self, **kwargs):
        self.annotation_events.append(dict(kwargs))
        return True

    def _patch_session(self, session_id, method, json_body):
        return self.app.test_request_context(
            f"/v2/admin/students/{self.user_id}/sessions/{session_id}",
            method=method,
            json=json_body,
        )

    def _invoke_patch(self, json_body):
        with self._patch_session(self.session_id, "PATCH", json_body):
            v2.request.user_id = self.admin_id
            response, status = v2.v2_admin_student_session_detail.__wrapped__(
                self.user_id, self.session_id
            )
            return status, response.get_json()

    def test_approve_matches_ai_suggestion_emits_approve_events(self):
        status, payload = self._invoke_patch({
            "coach_approved_profile": AI_PROFILE,
            "coach_approved_task_id": AI_TASK_ID,
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["coach_approved_profile"], AI_PROFILE)
        self.assertEqual(payload["coach_approved_task_id"], AI_TASK_ID)
        self.assertIsNotNone(payload["coach_approved_at"])

        row = self.sessions[self.session_id]
        self.assertEqual(row["coach_approved_profile"], AI_PROFILE)
        self.assertEqual(row["coach_approved_task_id"], AI_TASK_ID)
        self.assertIsNotNone(row["coach_approved_at"])

        self.assertEqual(len(self.annotation_events), 2)
        profile_event = next(e for e in self.annotation_events if e["field_name"] == "coach_approved_profile")
        task_event = next(e for e in self.annotation_events if e["field_name"] == "coach_approved_task_id")
        for event in (profile_event, task_event):
            self.assertEqual(event["section_type"], "profile_approval")
            self.assertEqual(event["reason_chip"], "approve")
            self.assertEqual(event["created_by"], self.admin_id)
            self.assertEqual(event["session_id"], self.session_id)
        self.assertEqual(profile_event["ai_original_text"], AI_PROFILE)
        self.assertEqual(profile_event["coach_final_text"], AI_PROFILE)
        self.assertEqual(task_event["ai_original_text"], AI_TASK_ID)
        self.assertEqual(task_event["coach_final_text"], AI_TASK_ID)

    def test_override_with_different_profile_and_task_emits_override_events(self):
        status, payload = self._invoke_patch({
            "coach_approved_profile": OTHER_PROFILE,
            "coach_approved_task_id": OTHER_TASK_ID,
            "coach_approved_justification": "Student was clearly in Master territory; pauses were strategic.",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["coach_approved_profile"], OTHER_PROFILE)
        self.assertEqual(payload["coach_approved_task_id"], OTHER_TASK_ID)

        profile_event = next(e for e in self.annotation_events if e["field_name"] == "coach_approved_profile")
        task_event = next(e for e in self.annotation_events if e["field_name"] == "coach_approved_task_id")
        self.assertEqual(profile_event["reason_chip"], "override")
        self.assertEqual(task_event["reason_chip"], "override")
        self.assertEqual(profile_event["ai_original_text"], AI_PROFILE)
        self.assertEqual(profile_event["coach_final_text"], OTHER_PROFILE)
        self.assertIn("Master", profile_event["custom_reason"])

    def test_invalid_profile_value_rejected_400(self):
        status, payload = self._invoke_patch({"coach_approved_profile": "The Procrastinator"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertEqual(self.sessions[self.session_id]["coach_approved_profile"], None)
        self.assertEqual(self.annotation_events, [])

    def test_non_behavioral_task_rejected_400(self):
        status, payload = self._invoke_patch({"coach_approved_task_id": LEGACY_TASK_ID})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertEqual(self.sessions[self.session_id]["coach_approved_task_id"], None)
        self.assertEqual(self.annotation_events, [])

    def test_unknown_task_rejected_400(self):
        status, payload = self._invoke_patch({"coach_approved_task_id": "99999999-9999-4999-8999-999999999999"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")

    def test_task_profile_mismatch_rejected_400(self):
        status, payload = self._invoke_patch({
            "coach_approved_profile": OTHER_PROFILE,
            "coach_approved_task_id": STRESSOR_TASK_ID,
        })
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertIn("Stressor", payload["error"])
        self.assertEqual(self.sessions[self.session_id]["coach_approved_profile"], None)
        self.assertEqual(self.sessions[self.session_id]["coach_approved_task_id"], None)
        self.assertEqual(self.annotation_events, [])

    def test_clearing_approved_fields_persists_null(self):
        self.sessions[self.session_id]["coach_approved_profile"] = AI_PROFILE
        self.sessions[self.session_id]["coach_approved_task_id"] = AI_TASK_ID
        status, payload = self._invoke_patch({
            "coach_approved_profile": None,
            "coach_approved_task_id": None,
        })
        self.assertEqual(status, 200)
        self.assertIsNone(payload["coach_approved_profile"])
        self.assertIsNone(payload["coach_approved_task_id"])
        self.assertIsNotNone(payload["coach_approved_at"])

    def test_touching_only_profile_stamps_timestamp_and_emits_one_event(self):
        status, payload = self._invoke_patch({"coach_approved_profile": OTHER_PROFILE})
        self.assertEqual(status, 200)
        self.assertEqual(payload["coach_approved_profile"], OTHER_PROFILE)
        self.assertIsNone(payload["coach_approved_task_id"])
        self.assertIsNotNone(payload["coach_approved_at"])
        self.assertEqual(len(self.annotation_events), 1)
        self.assertEqual(self.annotation_events[0]["field_name"], "coach_approved_profile")


if __name__ == "__main__":
    unittest.main()
