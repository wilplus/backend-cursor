"""willab coach per-snippet immediate save (E1 / §B.3 / S.5) — lane split.

Proves the split-sink at the WRITE boundary:
  * label      -> db.upsert_training_labels (PRIVATE) only
  * note/tag.. -> db.upsert_coach_snippet_draft (USER) only
  * no cross-derivation (the tag never lands in the label write, nor vice-versa)
  * partial saves are first-class; vocab is validated; snippet must be in-session.

The view is invoked via __wrapped__ (bypassing the auth decorator — auth is
covered by test_coach_auth) so this runs locally without a JWT.

Run: python3 -m unittest test_coach_snippet_save
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SNIP = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER_SNIP = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach save tests need app deps: {_IMPORT_ERROR}")
class PerSnippetSaveTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.label_calls = []
        self.draft_calls = []
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {"id": sid, "user_id": "u1"})
        self._patch_db("get_snippets_by_session", lambda sid: [{"id": SNIP}])
        self._patch_db("upsert_training_labels", self._fake_labels)
        self._patch_db("upsert_coach_snippet_draft", self._fake_draft)

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)

    def _patch_db(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr))
        setattr(v2.db, attr, fn)

    def _fake_labels(self, session_id, actor, rows):
        self.label_calls.append((session_id, actor, rows))
        return len(rows)

    def _fake_draft(self, session_id, snippet_id, fields, updated_by=None):
        self.draft_calls.append((session_id, snippet_id, dict(fields), updated_by))
        return {"session_id": session_id, "snippet_id": snippet_id, **fields}

    def _call(self, body, snip=SNIP):
        with self.app.test_request_context(json=body):
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_save_snippet.__wrapped__(SID, snip)
            return status, resp.get_json()

    # ── lane separation ──
    def test_label_only_writes_private_lane_only(self):
        status, data = self._call({"label": "challenge"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.label_calls), 1)
        self.assertEqual(len(self.draft_calls), 0)          # USER lane untouched
        self.assertEqual(self.label_calls[0][2][0]["value"], "challenge")
        self.assertEqual(data["saved"].get("label"), {"value": "challenge"})
        self.assertNotIn("draft", data["saved"])

    def test_note_tag_writes_user_lane_only(self):
        status, data = self._call({"note": "great pause here", "tag": "strong"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.draft_calls), 1)
        self.assertEqual(len(self.label_calls), 0)          # PRIVATE lane untouched
        self.assertEqual(self.draft_calls[0][2]["note"], "great pause here")
        self.assertEqual(self.draft_calls[0][2]["tag"], "strong")
        self.assertNotIn("label", data["saved"])

    def test_both_lanes_separate_writes_no_cross_derivation(self):
        status, _ = self._call({"label": "threat", "note": "shaky", "tag": "to_work_on"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.label_calls), 1)
        self.assertEqual(len(self.draft_calls), 1)
        # the tag never lands in the label write; the label never lands in the draft.
        self.assertNotIn("tag", self.label_calls[0][2][0])
        self.assertNotIn("value", self.draft_calls[0][2])
        self.assertNotIn("label", self.draft_calls[0][2])

    # ── partial saves (resume) ──
    def test_surfaced_only_partial_save(self):
        status, _ = self._call({"surfaced": False})
        self.assertEqual(status, 200)
        self.assertEqual(self.draft_calls[0][2], {"surfaced": False})
        self.assertEqual(len(self.label_calls), 0)

    def test_empty_note_clears(self):
        status, _ = self._call({"note": "   "})
        self.assertEqual(status, 200)
        self.assertIsNone(self.draft_calls[0][2]["note"])

    # ── vocab validation ──
    def test_bad_label_value_422_no_writes(self):
        status, _ = self._call({"label": "good"})  # not in direction-v1 vocab
        self.assertEqual(status, 422)
        self.assertEqual(len(self.label_calls), 0)
        self.assertEqual(len(self.draft_calls), 0)

    def test_bad_tag_422(self):
        status, _ = self._call({"tag": "amazing"})
        self.assertEqual(status, 422)
        self.assertEqual(len(self.draft_calls), 0)

    def test_surfaced_non_bool_422(self):
        status, _ = self._call({"surfaced": "yes"})
        self.assertEqual(status, 422)

    # ── scope guards ──
    def test_snippet_not_in_session_404(self):
        status, _ = self._call({"label": "challenge"}, snip=OTHER_SNIP)
        self.assertEqual(status, 404)
        self.assertEqual(len(self.label_calls), 0)

    def test_session_not_found_404(self):
        setattr(v2.db, "v2_get_session_by_id", lambda sid: None)
        status, _ = self._call({"label": "challenge"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
