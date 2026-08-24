"""Canonical exact-evidence coach publish contract.

Exercises the SHARED _apply_willab_publish_contract directly with stubbed db
methods (the real validators run). Covers:
  * surfaced drafts become exact-evidence FeedbackItems;
  * an empty set is a valid "no changes needed" result;
  * the take-level summary is persisted separately;
  * legacy insights_payload input is rejected;
  * delivery side effects remain intact.

Run: python3 -m unittest test_coach_publish
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    v2 = None
    _IMPORT_ERROR = e


SID = "11111111-1111-4111-8111-111111111111"
SNIP1 = "snip-1"
SNIP2 = "snip-2"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach publish tests need app deps: {_IMPORT_ERROR}")
class PublishContractTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.captured = {}
        self.originals = {}
        self.drafts = []
        self.snippets = [{"id": SNIP1}]
        self.session_row = {
            "id": SID, "user_id": "u1", "coach_video_ref": None,
            "project_id": "project-1", "coach_overall_message": None,
            "take_index": 2,
            "intake_context": {"topic": "Q3 pitch"},
        }

        self._patch_db("get_coach_snippet_drafts", lambda sid: self.drafts)
        self._patch_db("get_snippets_by_session", lambda sid: self.snippets)
        self._patch_db("v2_get_session_by_id", lambda sid: dict(self.session_row))
        self._patch_db("get_snippet_by_id", self._get_snippet)
        self._patch_db("upsert_coach_snippet_draft", self._capture_item)
        self._patch_db(
            "set_session_coach_overall_message", self._capture_summary,
        )
        self._patch_db("insert_lounge_messages", self._capture_lounge)
        self._patch_db("v2_charge_lab_credits_once", lambda *a, **k: None)
        self._patch_db("v2_charge_feedback_credits_once", lambda *a, **k: None)
        self._patch_db("v2_ensure_credits_initialized", lambda *a, **k: 15)

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)

    def _patch_db(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr, None))
        setattr(v2.db, attr, fn)

    def _get_snippet(self, snippet_id):
        return {
            "id": snippet_id,
            "session_id": SID,
            "start_offset_ms": 100,
            "duration_ms": 900,
        }

    def _capture_item(self, session_id, snippet_id, fields, updated_by=None):
        self.captured.setdefault("items", []).append({
            "session_id": session_id,
            "snippet_id": snippet_id,
            "fields": fields,
            "updated_by": updated_by,
        })
        return fields

    def _capture_summary(self, session_id, message):
        self.captured["summary"] = message
        return True

    def _capture_lounge(self, user_id, messages):
        self.captured["lounge"] = messages
        return [{"id": "srv", **m} for m in messages]

    def _run(self, body):
        document = {
            "pieces": [{
                "snippet_id": SNIP1, "slide_index": 0,
                "start": 0, "end": 12, "text": "Clear words.",
            }],
            "paragraphs": [{"start": 0, "end": 12}],
        }
        with self.app.test_request_context(), patch(
            "services.transcript_document.build_transcript_document",
            return_value=document,
        ):
            return v2._apply_willab_publish_contract(SID, body, "coach-1")

    def test_publishes_exact_evidence_feedback_and_summary(self):
        self.drafts = [{
            "snippet_id": SNIP1, "surfaced": True, "note": "great pause",
            "tag": "strong", "when_context": None, "examples": [],
        }]
        err = self._run({"notify_client": True, "overall_message": "well done"})
        self.assertIsNone(err)
        self.assertEqual(self.captured["summary"], "well done")
        item = self.captured["items"][0]
        self.assertEqual(item["snippet_id"], SNIP1)
        self.assertEqual(item["fields"]["feedback_family"], "great_formulation")
        evidence = item["fields"]["evidence_locator"]
        self.assertEqual(evidence["project_id"], "project-1")
        self.assertEqual(evidence["take_id"], SID)
        self.assertEqual(evidence["piece_id"], SNIP1)

    def test_insight_card_carries_topic_and_take_index(self):
        # F4 — the "insights ready" card metadata carries topic + take_index so
        # the FE reads "Feedback on {topic} (Take N)" instead of the date.
        self.drafts = [{
            "snippet_id": SNIP1, "surfaced": True, "note": "n",
            "tag": "strong", "when_context": None, "examples": [],
        }]
        self._run({"notify_client": True, "overall_message": "ok"})
        meta = self.captured["lounge"][0]["metadata"]
        self.assertEqual(meta["topic"], "Q3 pitch")
        self.assertEqual(meta["take_index"], 2)
        self.assertEqual(meta["session_id"], SID)

    def test_unsurfaced_draft_is_not_published(self):
        self.drafts = [
            {"snippet_id": SNIP1, "surfaced": True, "note": "shown", "tag": "strong"},
            {"snippet_id": SNIP2, "surfaced": False, "note": "hidden", "tag": "to_work_on"},
        ]
        err = self._run({"notify_client": True})
        self.assertIsNone(err)
        self.assertEqual(
            [item["snippet_id"] for item in self.captured["items"]],
            [SNIP1],
        )

    def test_private_annotations_do_not_gate_feedback(self):
        self.drafts = [{"snippet_id": SNIP1, "surfaced": True, "note": "x", "tag": "strong"}]
        self.snippets = [{"id": SNIP1}, {"id": SNIP2}]
        err = self._run({"notify_client": True})
        self.assertIsNone(err)

    def test_empty_feedback_is_valid_no_changes_needed(self):
        self.drafts = []
        err = self._run({"notify_client": True})
        self.assertIsNone(err)
        self.assertNotIn("items", self.captured)
        self.assertIn("lounge", self.captured)

    def test_coach_video_remains_on_the_take(self):
        self.drafts = [{"snippet_id": SNIP1, "surfaced": True, "note": "x", "tag": "strong"}]
        self.session_row["coach_video_ref"] = "https://cdn/v.mp4"
        err = self._run({"notify_client": True})
        self.assertIsNone(err)
        self.assertEqual(self.session_row["coach_video_ref"], "https://cdn/v.mp4")

    def test_legacy_insights_payload_is_rejected(self):
        body = {
            "insights_payload": {
                "overall_message": "from body",
                "snippet_notes": [{"snippet_id": SNIP1, "note": "body note", "tag": "strong"}],
            },
        }
        err = self._run(body)
        self.assertIsNotNone(err)
        response, status = err
        self.assertEqual(status, 422)
        self.assertEqual(response.get_json()["code"], "INVALID_INPUT")

if __name__ == "__main__":
    unittest.main()
