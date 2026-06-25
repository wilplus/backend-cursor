"""willab coach publish rewire (3c) — assemble-from-drafts + relaxed label
floor + library floor + coach-video fold + back-compat.

Exercises the SHARED _apply_willab_publish_contract directly with stubbed db
methods (the real validators run). Covers:
  * assemble mode (post-§F.4): {overall_message, notify_client} -> insights_
    payload built from persisted drafts; labels from training_labels.
  * relaxed gate: labels NEVER block publish (S.5) — require_all=False.
  * LIBRARY floor still enforced: no surfaced note -> 422.
  * coach video_ref folded into the published insights (B.3).
  * body mode (today's FE) unchanged: payload comes from the body, not drafts.
  * legacy publish (no insights_payload / no notify_client) -> untouched.

Plus the validate_publish_labels require_all unit.

Run: python3 -m unittest test_coach_publish
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask
    from routes import v2_routes as v2
    from services.training_labels import (
        validate_publish_labels, TrainingLabelError,
    )
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
        self.labels = []
        self.snippets = [{"id": SNIP1}]
        self.session_row = {
            "id": SID, "user_id": "u1", "coach_video_ref": None,
            "take_index": 2,
            "intake_context": {"topic": "Q3 pitch"},
        }

        self._patch_db("get_coach_snippet_drafts", lambda sid: self.drafts)
        self._patch_db("get_training_labels", lambda sid: self.labels)
        self._patch_db("get_snippets_by_session", lambda sid: self.snippets)
        self._patch_db("v2_get_session_by_id", lambda sid: dict(self.session_row))
        self._patch_db("set_session_insights_payload", self._capture_insights)
        self._patch_db("upsert_training_labels", self._capture_labels)
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

    def _capture_insights(self, session_id, payload):
        self.captured["insights"] = payload
        return True

    def _capture_labels(self, session_id, actor, rows):
        self.captured["labels"] = rows
        return len(rows)

    def _capture_lounge(self, user_id, messages):
        self.captured["lounge"] = messages
        return [{"id": "srv", **m} for m in messages]

    def _run(self, body):
        with self.app.test_request_context():
            return v2._apply_willab_publish_contract(SID, body, "coach-1")

    # ── assemble mode (post-§F.4) ──
    def test_assemble_builds_insights_from_drafts(self):
        self.drafts = [{
            "snippet_id": SNIP1, "surfaced": True, "note": "great pause",
            "tag": "strong", "when_context": None, "examples": [],
        }]
        self.labels = [{"snippet_id": SNIP1, "value": "challenge"}]
        err = self._run({"notify_client": True, "overall_message": "well done"})
        self.assertIsNone(err)                                   # success
        ins = self.captured["insights"]
        self.assertEqual(ins["overall_message"], "well done")
        self.assertEqual(len(ins["snippet_notes"]), 1)
        self.assertEqual(ins["snippet_notes"][0]["note"], "great pause")
        self.assertEqual(ins["snippet_notes"][0]["tag"], "strong")

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

    def test_unsurfaced_draft_excluded_from_insights(self):
        self.drafts = [
            {"snippet_id": SNIP1, "surfaced": True, "note": "shown", "tag": "strong"},
            {"snippet_id": SNIP2, "surfaced": False, "note": "hidden", "tag": "to_work_on"},
        ]
        err = self._run({"notify_client": True})
        self.assertIsNone(err)
        notes = self.captured["insights"]["snippet_notes"]
        self.assertEqual([n["snippet_id"] for n in notes], [SNIP1])  # unsurfaced dropped

    # ── relaxed label gate (S.5) ──
    def test_labels_not_required_to_publish(self):
        # Floor met (1 surfaced note) but 2 snippets, 0 labels — old gate would 422.
        self.drafts = [{"snippet_id": SNIP1, "surfaced": True, "note": "x", "tag": "strong"}]
        self.labels = []
        self.snippets = [{"id": SNIP1}, {"id": SNIP2}]
        err = self._run({"notify_client": True})
        self.assertIsNone(err)                                   # publishes anyway

    # ── library floor STILL enforced ──
    def test_no_surfaced_note_rejected_422(self):
        self.drafts = []  # nothing surfaced -> library floor fails
        err = self._run({"notify_client": True})
        self.assertIsNotNone(err)
        resp, status = err
        self.assertEqual(status, 422)
        self.assertEqual(resp.get_json()["code"], "PUBLISH_CONTRACT_VIOLATION")
        self.assertNotIn("insights", self.captured)              # nothing persisted

    # ── coach video fold (B.3) ──
    def test_coach_video_ref_folded(self):
        self.drafts = [{"snippet_id": SNIP1, "surfaced": True, "note": "x", "tag": "strong"}]
        self.session_row = {"id": SID, "user_id": "u1", "coach_video_ref": "https://cdn/v.mp4"}
        err = self._run({"notify_client": True})
        self.assertIsNone(err)
        self.assertEqual(self.captured["insights"].get("video_ref"), "https://cdn/v.mp4")

    # ── body mode (today's FE) unchanged ──
    def test_body_mode_uses_body_not_drafts(self):
        self.drafts = [{"snippet_id": SNIP2, "surfaced": True, "note": "DRAFT", "tag": "to_work_on"}]
        body = {
            "insights_payload": {
                "overall_message": "from body",
                "snippet_notes": [{"snippet_id": SNIP1, "note": "body note", "tag": "strong"}],
            },
            "labels": [{"snippet_id": SNIP1, "value": "threat"}],
        }
        err = self._run(body)
        self.assertIsNone(err)
        ins = self.captured["insights"]
        self.assertEqual(ins["overall_message"], "from body")
        self.assertEqual(ins["snippet_notes"][0]["note"], "body note")  # body wins; drafts ignored

    # ── legacy publish untouched ──
    def test_legacy_publish_returns_none_no_persist(self):
        err = self._run({"final_human_comment": "legacy"})  # no insights_payload, no notify_client
        self.assertIsNone(err)
        self.assertNotIn("insights", self.captured)         # opt-out: nothing happened


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RequireAllFlagTests(unittest.TestCase):
    def test_require_all_true_missing_raises(self):
        with self.assertRaises(TrainingLabelError):
            validate_publish_labels(
                [{"snippet_id": "a", "value": "threat"}], {"a", "b"}, require_all=True,
            )

    def test_require_all_false_missing_ok(self):
        cleaned = validate_publish_labels(
            [{"snippet_id": "a", "value": "threat"}], {"a", "b"}, require_all=False,
        )
        self.assertEqual(len(cleaned), 1)

    def test_require_all_false_still_rejects_bad_value(self):
        with self.assertRaises(TrainingLabelError):
            validate_publish_labels(
                [{"snippet_id": "a", "value": "nope"}], {"a"}, require_all=False,
            )


if __name__ == "__main__":
    unittest.main()
