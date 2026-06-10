"""UX Wave 3 — backend: audit assembly, suggested_action, progress + coach
drill-down/recut route shapes.

Module-level stubs for supabase + services.db (set in setUpModule, RESTORED
in tearDownModule — never bare-pop; a leaked stub corrupts sibling tests) let
the pure assembly + master_doc logic run without the venv. Route tests mirror
the test_coach_session harness (skip locally without flask, run in CI).

Run: python3 -m unittest test_wave3_be
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

_ORIG_SERVICES_DB = None
_ORIG_SUPABASE = None


def setUpModule():
    global _ORIG_SERVICES_DB, _ORIG_SUPABASE
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    _ORIG_SUPABASE = sys.modules.get("supabase")
    sys.modules["supabase"] = MagicMock()
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)
    if _ORIG_SUPABASE is not None:
        sys.modules["supabase"] = _ORIG_SUPABASE
    else:
        sys.modules.pop("supabase", None)


class UserAuditAssemblyTests(unittest.TestCase):
    """BE-3 / S5 — assembled from existing insights + library; unlock gate."""

    def _configure(self, *, recorded, sessions, library):
        from services.db import db
        db.v2_get_cumulative_recorded_seconds.return_value = recorded
        db.v2_list_user_lab_sessions.return_value = sessions
        db.get_strong_sides_library.return_value = library

    def test_assembles_published_only_and_unlock(self):
        self._configure(
            recorded=700,
            sessions=[
                {"id": "s1", "results_published_at": "2026-06-01T00:00:00Z",
                 "intake_context": {"topic": "demo day"}, "created_at": "2026-06-01",
                 "insights_payload": {"overall_message": "strong open", "snippet_notes": [
                     {"note": "great hook", "tag": "strong", "when": "opening",
                      "examples": ["that line"]}]}},
                # unpublished → excluded (no coach insights yet)
                {"id": "s2", "results_published_at": None,
                 "intake_context": {"topic": "draft"}, "created_at": "2026-06-02",
                 "insights_payload": {}},
            ],
            library=[
                {"note": "keep this", "tag": "strong",
                 "snippet_ref": {"transcript": "hello world"}, "session_id": "s1"},
                {"note": "watch this", "tag": "to_work_on",
                 "snippet_ref": {}, "session_id": "s1"},
            ],
        )
        from services.user_audit import assemble_user_audit
        a = assemble_user_audit("u1")
        self.assertTrue(a["unlocked"])
        self.assertEqual(a["recorded_seconds"], 700)
        self.assertEqual(a["threshold_seconds"], 600)
        self.assertEqual(len(a["sessions"]), 1)               # only the published one
        self.assertEqual(a["sessions"][0]["topic"], "demo day")
        self.assertEqual(a["sessions"][0]["notes"][0]["note"], "great hook")
        tags = {s["tag"] for s in a["strong_sides"]}
        self.assertEqual(tags, {"strong", "to_work_on"})

    def test_locked_under_threshold(self):
        self._configure(recorded=120, sessions=[], library=[])
        from services.user_audit import assemble_user_audit
        a = assemble_user_audit("u1")
        self.assertFalse(a["unlocked"])
        self.assertEqual(a["sessions"], [])
        self.assertEqual(a["strong_sides"], [])

    def test_html_render_is_safe_and_branded(self):
        from services.user_audit import render_user_audit_html
        html = render_user_audit_html({
            "strong_sides": [{"tag": "strong", "note": "<b>x</b>", "transcript": "hi"}],
        })
        self.assertIn("WillpowerLab", html)
        self.assertIn("&lt;b&gt;", html)   # escaped, not raw HTML injection


class SuggestedActionContractTests(unittest.TestCase):
    """BE-2 / S1 — every answer_question payload carries suggested_action."""

    def test_empty_question_payload_has_action_key(self):
        from services.master_doc_rag import answer_question
        payload, _debug = answer_question("")
        self.assertIn("suggested_action", payload)
        self.assertIsNone(payload["suggested_action"])

    def test_fallback_payload_has_action_key(self):
        from services.master_doc_rag import _fallback_payload
        self.assertIn("suggested_action", _fallback_payload())
        self.assertIsNone(_fallback_payload()["suggested_action"])

    def test_schema_declares_enum(self):
        from services.master_doc_rag import _RESPONSE_SCHEMA
        props = _RESPONSE_SCHEMA["schema"]["properties"]
        self.assertIn("suggested_action", props)
        self.assertIn("suggested_action", _RESPONSE_SCHEMA["schema"]["required"])
        enum = props["suggested_action"]["enum"]
        self.assertIn("strong_sides", enum)
        self.assertIn("record_again", enum)
        self.assertIn(None, enum)


# ── route shapes (skip locally without flask; run in CI) ──
try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _RT_ERR = e

UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class RecordingProgressRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._orig = getattr(v2.db, "v2_get_cumulative_recorded_seconds", None)
        v2.db.v2_get_cumulative_recorded_seconds = lambda uid: 720

    def tearDown(self):
        if self._orig is not None:
            v2.db.v2_get_cumulative_recorded_seconds = self._orig

    def test_progress_shape_unlocked(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_user_recording_progress.__wrapped__()
            data = resp.get_json()
            self.assertEqual(status, 200)
            self.assertEqual(data["recorded_seconds"], 720)
            self.assertEqual(data["threshold_seconds"], 600)
            self.assertTrue(data["unlocked"])


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class CoachStudentDetailRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._o1 = getattr(v2.db, "get_user_profile", None)
        self._o2 = getattr(v2.db, "v2_list_user_lab_sessions", None)
        v2.db.get_user_profile = lambda uid: {"domain": "sales", "goal": "win deals"}
        v2.db.v2_list_user_lab_sessions = lambda uid: [
            {"id": "s1", "intake_context": {"topic": "pitch"},
             "created_at": "2026-06-01", "status": "pending_admin_review",
             "results_published_at": None},
        ]

    def tearDown(self):
        if self._o1 is not None:
            v2.db.get_user_profile = self._o1
        if self._o2 is not None:
            v2.db.v2_list_user_lab_sessions = self._o2

    def test_drilldown_pseudonymized_no_pii(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_student_detail.__wrapped__(UID)
            data = resp.get_json()
            self.assertEqual(status, 200)
            self.assertTrue(data["pseudonym"])
            self.assertEqual(data["domain"], "sales")
            self.assertEqual(data["goal"], "win deals")
            self.assertEqual(data["sessions"][0]["state"], "review_pending")
            self.assertNotIn("name", data)
            self.assertNotIn("email", data)
            self.assertNotIn(UID, str(data.get("pseudonym")))

    def test_unknown_id_returns_404(self):
        v2.db.v2_list_user_lab_sessions = lambda uid: []
        v2.db.get_user_profile = lambda uid: {}
        with self.app.test_request_context():
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_student_detail.__wrapped__(UID)
            self.assertEqual(status, 404)
            self.assertEqual(resp.get_json()["code"], "STUDENT_NOT_FOUND")


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class AuditSendGateTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_locked_audit_returns_409(self):
        import services.user_audit as ua
        orig = ua.assemble_user_audit
        ua.assemble_user_audit = lambda uid: {
            "unlocked": False, "recorded_seconds": 60, "threshold_seconds": 600,
        }
        try:
            with self.app.test_request_context():
                request.user_id = "coach-1"
                resp, status = v2.v2_coach_student_audit_send.__wrapped__(UID)
                self.assertEqual(status, 409)
                self.assertEqual(resp.get_json()["code"], "AUDIT_LOCKED")
        finally:
            ua.assemble_user_audit = orig


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class RecutGuardTests(unittest.TestCase):
    """BE-6 tightening — re-cut must refuse a PARTIALLY-REVIEWED session
    (existing labels/drafts) unless ?force=true, so coach training signal is
    never silently orphaned."""

    def setUp(self):
        self.app = Flask(__name__)
        self._o = getattr(v2.db, "v2_get_session_by_id", None)
        self._l = getattr(v2.db, "get_training_labels", None)
        self._d = getattr(v2.db, "get_coach_snippet_drafts", None)
        v2.db.v2_get_session_by_id = lambda sid: {
            "id": sid, "results_published_at": None, "recording_1_id": "r1",
        }
        v2.db.get_training_labels = lambda sid: [
            {"snippet_id": "a"}, {"snippet_id": "b"},
            {"snippet_id": "c"}, {"snippet_id": "d"},
        ]
        v2.db.get_coach_snippet_drafts = lambda sid: []

    def tearDown(self):
        if self._o is not None:
            v2.db.v2_get_session_by_id = self._o
        if self._l is not None:
            v2.db.get_training_labels = self._l
        if self._d is not None:
            v2.db.get_coach_snippet_drafts = self._d

    def test_refused_without_force_when_labels_exist(self):
        with self.app.test_request_context():  # no ?force
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_session_recut.__wrapped__(UID)
            self.assertEqual(status, 409)
            data = resp.get_json()
            self.assertEqual(data["code"], "RECUT_WOULD_DISCARD_LABELS")
            self.assertEqual(data["labels"], 4)


if __name__ == "__main__":
    unittest.main()
