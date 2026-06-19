"""willab coach per-snippet save — /v2/coach/sessions/<id>/snippets/<id>.

Aligned to FE PR #73: body uses `direction_label` (str|null; null clears),
the response echoes the folded `coach_state`. Proves the split-sink at the
WRITE boundary + the round-trip:
  * direction_label -> training_labels (PRIVATE) only
  * note/tag/surfaced -> coach_snippet_drafts (USER) only
  * no cross-derivation; surfaced defaults false; null direction clears.

Stateful db stubs (upsert writes, get reads) so the coach_state echo reflects
what's persisted. View invoked via __wrapped__ (auth covered by test_coach_auth).
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
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
        self.labels: dict = {}   # snippet_id -> value (PRIVATE store)
        self.drafts: dict = {}   # snippet_id -> {note,tag,surfaced} (USER store)
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {"id": sid, "user_id": "u1"})
        self._patch_db("get_snippets_by_session", lambda sid: [{"id": SNIP}])
        self._patch_db("upsert_training_labels", self._upsert_labels)
        self._patch_db("delete_training_label", self._delete_label)
        self._patch_db("upsert_coach_snippet_draft", self._upsert_draft)
        self._patch_db("get_training_labels", self._get_labels)
        self._patch_db("get_coach_snippet_drafts", self._get_drafts)

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)

    def _patch_db(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr, None))
        setattr(v2.db, attr, fn)

    # stateful fakes
    def _upsert_labels(self, sid, actor, rows):
        for r in rows:
            self.labels[r["snippet_id"]] = r["value"]
        return len(rows)

    def _delete_label(self, sid, snip):
        self.labels.pop(snip, None)
        return True

    def _upsert_draft(self, sid, snip, fields, updated_by=None):
        # §1.A opt-out-surface — first write defaults surfaced=True (mirrors
        # db.upsert_coach_snippet_draft). Coach UN-surface persists explicitly.
        d = self.drafts.setdefault(snip, {"note": None, "tag": None, "surfaced": True})
        d.update(fields)
        return d

    def _get_labels(self, sid):
        return [{"snippet_id": k, "value": v} for k, v in self.labels.items()]

    def _get_drafts(self, sid):
        return [{"snippet_id": k, **v} for k, v in self.drafts.items()]

    def _call(self, body, snip=SNIP):
        with self.app.test_request_context(json=body):
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_save_snippet.__wrapped__(SID, snip)
            return status, resp.get_json()

    # ── lane separation + echo ──
    def test_direction_label_private_lane_and_echo(self):
        status, data = self._call({"direction_label": "challenge"})
        self.assertEqual(status, 200)
        self.assertEqual(self.labels[SNIP], "challenge")        # PRIVATE write
        self.assertEqual(self.drafts, {})                        # USER untouched
        self.assertEqual(data["coach_state"]["direction_label"], "challenge")

    def test_note_tag_user_lane_and_echo(self):
        status, data = self._call({"note": "nice open", "tag": "strong"})
        self.assertEqual(status, 200)
        self.assertEqual(self.drafts[SNIP]["note"], "nice open")
        self.assertEqual(self.drafts[SNIP]["tag"], "strong")
        self.assertEqual(self.labels, {})                        # PRIVATE untouched
        self.assertEqual(data["coach_state"]["note"], "nice open")
        self.assertEqual(data["coach_state"]["tag"], "strong")

    def test_both_lanes_no_cross_derivation(self):
        self._call({"direction_label": "threat", "note": "x", "tag": "to_work_on"})
        self.assertEqual(self.labels[SNIP], "threat")
        self.assertNotIn("value", self.drafts[SNIP])             # tag store has no label value
        self.assertNotIn("direction_label", self.drafts[SNIP])

    # ── null clears the label ──
    def test_null_direction_clears(self):
        self._call({"direction_label": "challenge"})
        self.assertEqual(self.labels[SNIP], "challenge")
        status, data = self._call({"direction_label": None})
        self.assertNotIn(SNIP, self.labels)                      # cleared
        self.assertIsNone(data["coach_state"]["direction_label"])

    # ── surfaced defaults TRUE (§1.A opt-out-surface) ──
    def test_note_defaults_to_surfaced(self):
        # A note-only save now reaches the user by default; the coach
        # explicitly UN-surfaces to hide (§1.A FE handoff 2026-06-19).
        status, data = self._call({"note": "shown by default"})
        self.assertTrue(self.drafts[SNIP]["surfaced"])
        self.assertTrue(data["coach_state"]["surfaced"])

    def test_explicit_unsurface_persists(self):
        # Coach hides a snippet: explicit surfaced=false sticks.
        status, data = self._call({"note": "hide me", "surfaced": False})
        self.assertFalse(self.drafts[SNIP]["surfaced"])
        self.assertFalse(data["coach_state"]["surfaced"])

    def test_explicit_surface(self):
        status, data = self._call({"surfaced": True})
        self.assertTrue(self.drafts[SNIP]["surfaced"])
        self.assertTrue(data["coach_state"]["surfaced"])

    # ── vocab + scope ──
    def test_bad_direction_422(self):
        status, _ = self._call({"direction_label": "good"})
        self.assertEqual(status, 422)
        self.assertEqual(self.labels, {})

    def test_bad_tag_422(self):
        status, _ = self._call({"tag": "amazing"})
        self.assertEqual(status, 422)

    def test_snippet_not_in_session_404(self):
        status, _ = self._call({"direction_label": "challenge"}, snip=OTHER_SNIP)
        self.assertEqual(status, 404)
        self.assertEqual(self.labels, {})

    def test_session_not_found_404(self):
        setattr(v2.db, "v2_get_session_by_id", lambda sid: None)
        status, _ = self._call({"direction_label": "challenge"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
