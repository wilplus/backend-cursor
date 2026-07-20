"""willab — persist the student's in-place SD ideal-text edit (founder
2026-07-17). The post-recording screen IS the ideal text 1.0, editable in
place; this suite pins the persistence seam:

  BE-1  PUT round-trip + version stamping; 409 on a stale version; HTML
        stripped; markers survive verbatim.
  BE-2  display-priority matrix on the student GET: user edit wins ONLY
        while its version == the current version (a new take supersedes it);
        user_edited flag.
  BE-3  the coach GET carries user_edit as read-only reference.

Run: python3 -m unittest test_user_ideal_edit
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e

ARC = "a1"
SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"
SESS = "bbbb2222-bbbb-2222-bbbb-222222222222"


def _row(**over):
    row = {"arc_id": ARC, "text": "machine text", "auto_text": "machine text",
           "updated_by": None, "approved_at": None, "version": 3,
           "verified_version": None, "verified_text": None}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UserEditPutTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _put(self, body, *, row=_row(), owned=True):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "upsert_user_ideal_edit",
                              return_value=True) as m_up:
                out = v2.v2_explore_put_ideal_user_edit.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_up

    def test_saves_against_current_version(self):
        body, status, m_up = self._put({"text": "my edit", "version": 3})
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        self.assertEqual(body["version"], 3)
        # stamped with the CURRENT version (which equals the provided one)
        self.assertEqual(m_up.call_args.args[2], "my edit")
        self.assertEqual(m_up.call_args.args[3], 3)

    def test_stale_version_409_with_current(self):
        # edit made against v2 but v3 has assembled since → refetch signal
        body, status, m_up = self._put({"text": "old edit", "version": 2})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "VERSION_SUPERSEDED")
        self.assertEqual(body["current_version"], 3)
        m_up.assert_not_called()

    def test_html_stripped_markers_survive(self):
        body, status, m_up = self._put({
            "text": "<b>bold</b> **kept** [[moment:x|y]]m[[/moment]]",
            "version": 3})
        self.assertEqual(status, 200)
        saved = m_up.call_args.args[2]
        self.assertNotIn("<b>", saved)
        self.assertIn("**kept**", saved)          # FE markers ride through
        self.assertIn("[[moment:x|y]]", saved)

    def test_bad_version_and_text_400(self):
        _, s1, _ = self._put({"text": "x", "version": 0})
        _, s2, _ = self._put({"text": "x", "version": "3"})
        _, s3, _ = self._put({"text": "x", "version": True})
        _, s4, _ = self._put({"version": 3})       # no text
        self.assertEqual((s1, s2, s3, s4), (400, 400, 400, 400))

    def test_nothing_to_edit_when_no_version(self):
        body, status, m_up = self._put(
            {"text": "x", "version": 1}, row=None)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "NOTHING_TO_EDIT")
        m_up.assert_not_called()

    def test_unowned_404(self):
        _, status, m_up = self._put({"text": "x", "version": 3}, owned=False)
        self.assertEqual(status, 404)
        m_up.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LedgerInheritanceTests(unittest.TestCase):
    """Rule 4b (founder 2026-07-20): the saved edit decomposes into
    phrase-level APPROVED ledger rows (source='user_edit') so the next
    assembly bakes the student's wording forward. Wholesale rewrites and
    ledger failures write nothing and never break the save."""

    def setUp(self):
        self.app = Flask(__name__)

    def _put(self, text, *, row):
        with self.app.test_request_context(
                json={"text": text, "version": row.get("version")}):
            request.user_id = "u1"
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "upsert_user_ideal_edit",
                              return_value=True), \
                 patch.object(v2.db, "upsert_ideal_decision",
                              return_value=True) as m_led:
                out = v2.v2_explore_put_ideal_user_edit.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_led

    def test_edit_lands_as_phrase_rows(self):
        row = _row(version=2,
                   auto_text="we kept showing up every single day")
        body, status, m_led = self._put(
            "we stayed relentless every single day", row=row)
        self.assertEqual(status, 200)
        kw = m_led.call_args.kwargs
        self.assertEqual(kw["kind"], "replace")
        self.assertEqual(kw["decision"], "approved")
        self.assertEqual(kw["source"], "user_edit")
        self.assertEqual(kw["target_phrase"], "kept showing up")
        self.assertEqual(kw["replacement_text"], "stayed relentless")
        self.assertEqual(kw["version"], 2)

    def test_verified_current_version_diffs_against_snapshot(self):
        row = _row(version=2, verified_version=2,
                   verified_text="we kept showing up every single day",
                   auto_text="a stale machine copy")
        body, status, m_led = self._put(
            "we stayed relentless every single day", row=row)
        self.assertEqual(status, 200)
        self.assertEqual(m_led.call_args.kwargs["target_phrase"],
                         "kept showing up")

    def test_wholesale_rewrite_writes_no_rows(self):
        row = _row(version=2, auto_text="alpha beta gamma delta epsilon")
        body, status, m_led = self._put(
            "completely different sentence with new words here", row=row)
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        m_led.assert_not_called()

    def test_ledger_failure_never_breaks_the_save(self):
        row = _row(version=2, auto_text="we kept going strong")
        with self.app.test_request_context(
                json={"text": "we kept moving strong", "version": 2}):
            request.user_id = "u1"
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "upsert_user_ideal_edit",
                              return_value=True), \
                 patch.object(v2.db, "upsert_ideal_decision",
                              side_effect=RuntimeError("boom")):
                out = v2.v2_explore_put_ideal_user_edit.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 200)
        self.assertTrue(resp.get_json()["saved"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentGetDisplayPriorityTests(unittest.TestCase):
    """BE-2 — the edit wins ONLY at the current version."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, row, edit):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2, "_single_deliverable_enabled",
                              return_value=True), \
                 patch.object(v2, "_moments_entitled", return_value=False), \
                 patch.object(v2, "_moment_explanations_map",
                              return_value={}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_ideal_edit",
                              return_value=edit), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value=None):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_edit_at_current_version_wins(self):
        body, _ = self._get(
            row=_row(version=3),
            edit={"text": "MY EDIT", "version": 3, "updated_at": "t"})
        self.assertEqual(body["text"], "MY EDIT")
        self.assertTrue(body["user_edited"])

    def test_stale_edit_does_not_win_shows_machine(self):
        # a new take bumped version to 3; the edit was against v2 → superseded
        body, _ = self._get(
            row=_row(version=3),
            edit={"text": "OLD EDIT", "version": 2, "updated_at": "t"})
        self.assertEqual(body["text"], "machine text")
        self.assertFalse(body["user_edited"])

    def test_edit_wins_over_verified_at_current_version(self):
        body, _ = self._get(
            row=_row(version=3, verified_version=3,
                     verified_text="COACH VERIFIED", updated_by="c",
                     text="coach working"),
            edit={"text": "STUDENT TWEAK", "version": 3, "updated_at": "t"})
        self.assertEqual(body["text"], "STUDENT TWEAK")
        self.assertTrue(body["user_edited"])
        self.assertEqual(body["status"], "verified")   # version is verified

    def test_no_edit_shows_base_text(self):
        body, _ = self._get(row=_row(version=3), edit=None)
        self.assertEqual(body["text"], "machine text")
        self.assertFalse(body["user_edited"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachGetUserEditTests(unittest.TestCase):
    """BE-3 — the coach GET carries the student's edit as read-only ref."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, sessions, edit, coach_row):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "get_user_ideal_edit",
                              return_value=edit) as m_edit, \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=coach_row), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       return_value=False), \
                 patch("services.ideal_text_block.assemble_ideal_text_block",
                       return_value={"text": "x", "key_moments": [],
                                     "ready": True}):
                out = v2.v2_coach_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_edit

    def test_coach_get_carries_user_edit_keyed_on_owner(self):
        edit = {"text": "student edit", "version": 3, "updated_at": "t"}
        body, status, m_edit = self._get(
            sessions=[{"id": "s1", "user_id": "owner-uid"}],
            edit=edit,
            coach_row={"text": "coach block", "updated_by": "coach1",
                       "approved_at": None, "version": 3})
        self.assertEqual(status, 200)
        self.assertEqual(body["user_edit"], edit)
        # looked up against the ARC OWNER, not the coach
        self.assertEqual(m_edit.call_args.args[1], "owner-uid")

    def test_coach_get_user_edit_null_when_none(self):
        body, _, _ = self._get(
            sessions=[{"id": "s1", "user_id": "owner-uid"}],
            edit=None,
            coach_row={"text": "coach block", "updated_by": "coach1",
                       "approved_at": None, "version": 3})
        self.assertIsNone(body["user_edit"])


if __name__ == "__main__":
    unittest.main()
