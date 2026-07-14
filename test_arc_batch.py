"""willab — arc batch delivery (founder 2026-07-13).

POST /v2/coach/arc/<arc_id>/publish  — the explicit "Publish arc" action
GET  /v2/explore/arc/<arc_id>/batch  — the student's one-batch review
GET  /v2/user/trainings              — the arc-grouped training tab
POST /v2/internal/publish-session-results — inline snippets[] save-at-publish

Route-level tests (the test_wave2_be.py / test_arc_unlock.py harness: patch
db.* on the v2 module, call the unwrapped handler in a test_request_context).

FENCES verified here:
  * the student batch NEVER carries say_it_stronger (synonyms are the instant
    readout's, only) — asserted against the serialized payload;
  * no private-lane direction values in the batch (BLIND COACH);
  * batch publish requires coach_finalized FIRST (the founder's order).

Run: python3 -m unittest test_arc_batch
"""
from __future__ import annotations

import json
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


def _sessions(n=3, user_id="u1", published=()):
    out = []
    for i in range(1, n + 1):
        out.append({
            "id": f"s{i}", "user_id": user_id, "arc_id": "a1",
            "take_index": i, "created_at": f"2026-07-1{i}T10:00:00Z",
            "intake_context": {"topic": "Quarterly sync",
                               "slides": [{"title": "One"}]},
            "results_published_at": (
                "2026-07-13T12:00:00Z" if i in published else None
            ),
        })
    return out


def _bp_payload(finalized=True, coach_edited_all=True):
    return {
        "ready": True,
        "progress": {"takes_done": 3, "takes_target": 3,
                     "takes_remaining": 0, "ready": True},
        "name": "Quarterly sync",
        "coach_reviewed": True,
        "coach_finalized": finalized,
        "presentation_ref": None,
        "slides": [
            {"index": 0, "title": "One", "body": "",
             "text": "Coach-corrected verbatim.",
             "coach_edited": coach_edited_all, "key_phrases": []},
        ],
    }


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachArcPublishTests(unittest.TestCase):
    """POST /v2/coach/arc/<arc_id>/publish."""

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, arc_id="a1", coach_id="coach1"):
        with self.app.test_request_context(json={}):
            request.user_id = coach_id
            resp, status = v2.v2_coach_arc_publish.__wrapped__(arc_id)
            return resp.get_json(), status

    def test_unknown_arc_404s(self):
        with patch.object(v2.db, "get_arc_sessions", return_value=[]):
            body, status = self._call()
        self.assertEqual(status, 404)

    def test_ideal_text_incomplete_409_with_pending_slides(self):
        # The founder order: coach edits the ideal text FIRST. Unfinalized →
        # 409 + which slides are pending; nothing published, nothing marked.
        with patch.object(v2.db, "get_arc_sessions",
                          return_value=_sessions()), \
             patch("services.best_presentation.build_best_presentation",
                   return_value=_bp_payload(finalized=False,
                                            coach_edited_all=False)), \
             patch.object(v2.db, "mark_arc_batch_delivered") as m_mark, \
             patch.object(v2.db, "v2_publish_session_results") as m_pub:
            body, status = self._call()
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "IDEAL_TEXT_INCOMPLETE")
        self.assertEqual(body["slides_pending"], [0])
        m_mark.assert_not_called()
        m_pub.assert_not_called()

    def test_happy_path_publishes_unpublished_takes_and_marks_delivered(self):
        drafts = [{"snippet_id": "sn1", "surfaced": True, "note": "Strong."}]
        with patch.object(v2.db, "get_arc_sessions",
                          return_value=_sessions(published=(1,))), \
             patch("services.best_presentation.build_best_presentation",
                   return_value=_bp_payload()), \
             patch.object(v2.db, "get_coach_snippet_drafts",
                          return_value=drafts), \
             patch.object(v2, "_apply_willab_publish_contract",
                          return_value=None) as m_contract, \
             patch.object(v2.db, "v2_update_session_status_unscoped"), \
             patch.object(v2.db, "v2_publish_session_results") as m_pub, \
             patch.object(v2.db, "mark_arc_batch_delivered",
                          return_value=True) as m_mark, \
             patch("services.arc_notifications."
                   "maybe_fire_best_presentation_ready") as m_fire:
            body, status = self._call()
        self.assertEqual(status, 200)
        self.assertTrue(body["published"])
        # take 1 already published → skipped; takes 2+3 published now.
        self.assertEqual(body["takes_published"], 2)
        self.assertEqual(body["takes_already_published"], 1)
        self.assertEqual(m_pub.call_count, 2)
        # The batch door suppresses the per-take Lounge card (ONE arc-level
        # notification instead) — assemble mode + the suppress flag.
        for call in m_contract.call_args_list:
            self.assertEqual(call.args[1], {
                "notify_client": False, "suppress_lounge_card": True,
            })
        m_mark.assert_called_once_with("a1", "u1", "coach1")
        m_fire.assert_called_once()

    def test_take_with_no_surfaced_notes_is_skipped_not_fatal(self):
        with patch.object(v2.db, "get_arc_sessions",
                          return_value=_sessions()), \
             patch("services.best_presentation.build_best_presentation",
                   return_value=_bp_payload()), \
             patch.object(v2.db, "get_coach_snippet_drafts",
                          return_value=[]), \
             patch.object(v2, "_apply_willab_publish_contract") as m_contract, \
             patch.object(v2.db, "v2_publish_session_results") as m_pub, \
             patch.object(v2.db, "mark_arc_batch_delivered",
                          return_value=True) as m_mark, \
             patch("services.arc_notifications."
                   "maybe_fire_best_presentation_ready"):
            body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["takes_published"], 0)
        self.assertEqual(body["takes_skipped_no_coach_notes"], 3)
        m_contract.assert_not_called()
        m_pub.assert_not_called()
        m_mark.assert_called_once()  # the batch marker still lands

    def test_contract_failure_aborts_without_marking_delivered(self):
        drafts = [{"snippet_id": "sn1", "surfaced": True, "note": "x"}]
        with self.app.test_request_context(json={}):
            request.user_id = "coach1"
            # jsonify needs the app context — build the error tuple inside.
            err = (v2.jsonify({"code": "PUBLISH_CONTRACT_VIOLATION"}), 422)
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=_sessions()), \
                 patch("services.best_presentation.build_best_presentation",
                       return_value=_bp_payload()), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              return_value=drafts), \
                 patch.object(v2, "_apply_willab_publish_contract",
                              return_value=err), \
                 patch.object(v2.db, "mark_arc_batch_delivered") as m_mark:
                resp, status = v2.v2_coach_arc_publish.__wrapped__("a1")
                body = resp.get_json()
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "TAKE_PUBLISH_FAILED")
        self.assertEqual(body["session_id"], "s1")
        m_mark.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentArcBatchTests(unittest.TestCase):
    """GET /v2/explore/arc/<arc_id>/batch."""

    def setUp(self):
        self.app = Flask(__name__)
        self._p = [
            patch.object(v2, "_arc_owned_by_caller",
                         lambda arc_id: (True, _sessions())),
            patch.object(v2, "_arc_payment_gate", lambda arc_id: None),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _call(self, arc_id="a1"):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_explore_arc_batch.__wrapped__(arc_id)
            return resp.get_json(), status

    def test_not_delivered_yet(self):
        with patch.object(v2.db, "get_arc_batch_delivery",
                          return_value=None):
            body, status = self._call()
        self.assertEqual(status, 200)
        self.assertFalse(body["delivered"])
        self.assertNotIn("takes", body)

    def _delivered_setup(self):
        delivery = {"arc_id": "a1", "published_at": "2026-07-13T15:00:00Z"}
        # Snippets carry say_it_stronger + metrics on the DB row — the batch
        # payload must hand-pick fields and DROP both.
        snips = [
            {"id": "sn1", "transcript": "raw machine words",
             "audio_segment_path": "https://x/p.webm",
             "start_offset_ms": 0, "duration_ms": 4000,
             "say_it_stronger": {"upgrades": [{"original": "good",
                                               "upgrade": "compelling"}]},
             "metrics": {"overall_score": 0.9}},
            {"id": "sn2", "transcript": "unsurfaced words",
             "audio_segment_path": "https://x/p.webm",
             "start_offset_ms": 5000, "duration_ms": 4000,
             "say_it_stronger": {"upgrades": []}},
        ]
        drafts = [
            {"snippet_id": "sn1", "surfaced": True, "note": "Land it here.",
             "tag": "strong", "when_context": None, "examples": [],
             "transcript_corrected": "coach corrected words",
             "breakthrough_video_ref": None},
            {"snippet_id": "sn2", "surfaced": False, "note": "hidden"},
        ]
        return delivery, snips, drafts

    def test_delivered_batch_shape_and_fences(self):
        delivery, snips, drafts = self._delivered_setup()
        with patch.object(v2.db, "get_arc_batch_delivery",
                          return_value=delivery), \
             patch.object(v2.db, "get_coach_snippet_drafts",
                          return_value=drafts), \
             patch.object(v2.db, "get_snippets_by_session",
                          return_value=snips), \
             patch("services.best_presentation.build_best_presentation",
                   return_value=_bp_payload()):
            body, status = self._call()
        self.assertEqual(status, 200)
        self.assertTrue(body["delivered"])
        self.assertEqual(body["delivered_at"], "2026-07-13T15:00:00Z")
        self.assertEqual(len(body["takes"]), 3)
        take1 = body["takes"][0]
        # ONLY the surfaced+noted snippet rides; the unsurfaced one doesn't.
        self.assertEqual(len(take1["snippets"]), 1)
        s = take1["snippets"][0]
        # L1: the coach-corrected verbatim IS the transcript served.
        self.assertEqual(s["transcript"], "coach corrected words")
        self.assertEqual(s["coach"]["note"], "Land it here.")
        self.assertEqual(s["coach"]["tag"], "strong")
        # Ideal text at the end (student view).
        self.assertEqual(body["ideal_text"]["slides"][0]["text"],
                         "Coach-corrected verbatim.")
        # ── FENCES on the whole serialized payload ──
        raw = json.dumps(body)
        # synonyms/rewrites are the instant readout's ONLY:
        self.assertNotIn("say_it_stronger", raw)
        self.assertNotIn("compelling", raw)   # the upgrade text itself
        # no private-lane direction values (BLIND COACH):
        self.assertNotIn("threat", raw)
        self.assertNotIn("challenge", raw)
        # no scores (AC-9):
        self.assertNotIn("overall_score", raw)

    def test_unowned_arc_404s(self):
        with patch.object(v2, "_arc_owned_by_caller",
                          lambda arc_id: (False, [])):
            body, status = self._call()
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UserTrainingsTests(unittest.TestCase):
    """GET /v2/user/trainings — arc-grouped, deckless included."""

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_user_list_trainings.__wrapped__()
            return resp.get_json(), status

    def test_groups_by_arc_and_includes_deckless(self):
        rows = [
            # decked arc a1, 2 takes
            {"id": "s1", "arc_id": "a1", "take_index": 1,
             "created_at": "2026-07-10T10:00:00Z",
             "intake_context": {"topic": "Deck talk",
                                "slides": [{"title": "One"}]},
             "results_published_at": "2026-07-11T09:00:00Z"},
            {"id": "s2", "arc_id": "a1", "take_index": 2,
             "created_at": "2026-07-11T10:00:00Z",
             "intake_context": {"topic": "Deck talk",
                                "slides": [{"title": "One"}]},
             "results_published_at": None},
            # DECKLESS arc a2 — must appear as its own training
            {"id": "s3", "arc_id": "a2", "take_index": 1,
             "created_at": "2026-07-12T10:00:00Z",
             "intake_context": {"topic": "No-deck story"},
             "results_published_at": None},
        ]
        with patch.object(v2.db, "list_user_arc_sessions",
                          return_value=rows), \
             patch.object(v2.db, "list_arc_batch_deliveries",
                          return_value={"a2": {
                              "arc_id": "a2",
                              "published_at": "2026-07-13T08:00:00Z"}}), \
             patch.object(v2.db, "get_coach_best_presentation_edits",
                          return_value={}):
            body, status = self._call()
        self.assertEqual(status, 200)
        trainings = body["trainings"]
        self.assertEqual(len(trainings), 2)
        by_arc = {t["arc_id"]: t for t in trainings}
        # deckless training exists, is batch_verified + ideal_ready via the
        # delivery row (its publish already required coach_finalized).
        a2 = by_arc["a2"]
        self.assertEqual(a2["topic"], "No-deck story")
        self.assertTrue(a2["batch_verified"])
        self.assertTrue(a2["ideal_ready"])
        self.assertEqual(a2["take_count"], 1)
        # decked training lists its takes in take order with reviewed flags.
        a1 = by_arc["a1"]
        self.assertFalse(a1["batch_verified"])
        self.assertEqual([t["take_index"] for t in a1["takes"]], [1, 2])
        self.assertTrue(a1["takes"][0]["coach_reviewed"])
        self.assertFalse(a1["takes"][1]["coach_reviewed"])
        self.assertEqual(a1["takes_target"], 3)
        # newest training first
        self.assertEqual(trainings[0]["arc_id"], "a2")

    def test_no_arcs_empty_list(self):
        with patch.object(v2.db, "list_user_arc_sessions", return_value=[]), \
             patch.object(v2.db, "list_arc_batch_deliveries",
                          return_value={}):
            body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["trainings"], [])

    def test_decked_ideal_ready_via_cheap_coach_finalized(self):
        rows = [{
            "id": "s1", "arc_id": "a1", "take_index": 1,
            "created_at": "2026-07-10T10:00:00Z",
            "intake_context": {"topic": "T",
                               "slides": [{"title": "A"}, {"title": "B"}]},
            "results_published_at": None,
        }]
        with patch.object(v2.db, "list_user_arc_sessions",
                          return_value=rows), \
             patch.object(v2.db, "list_arc_batch_deliveries",
                          return_value={}), \
             patch.object(v2.db, "get_coach_best_presentation_edits",
                          return_value={0: "Edited.", 1: "Also edited."}):
            body, status = self._call()
        self.assertTrue(body["trainings"][0]["ideal_ready"])
        self.assertFalse(body["trainings"][0]["batch_verified"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PublishInlineSnippetsTests(unittest.TestCase):
    """POST /v2/internal/publish-session-results with inline snippets[] —
    save-at-publish (the FE no longer autosaves per keystroke)."""

    SESSION_ID = "11111111-1111-1111-1111-111111111111"
    SNIP_ID = "22222222-2222-2222-2222-222222222222"

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, body):
        with self.app.test_request_context(json=body):
            request.user_id = "coach1"
            out = v2.v2_internal_publish_session_results.__wrapped__()
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def test_inline_snippets_persist_through_shared_lanes(self):
        session = {"id": self.SESSION_ID, "user_id": None}
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value=session), \
             patch.object(v2.db, "get_snippets_by_session",
                          return_value=[{"id": self.SNIP_ID}]), \
             patch.object(v2, "_save_coach_snippet_lanes",
                          return_value=None) as m_lanes, \
             patch.object(v2, "_apply_willab_publish_contract",
                          return_value=None), \
             patch.object(v2.db, "record_snippet_publish_annotations",
                          return_value=0), \
             patch.object(v2.db, "v2_update_session_status_unscoped"):
            body, status = self._call({
                "session_id": self.SESSION_ID,
                "notify_client": False,
                "snippets": [{
                    "id": self.SNIP_ID, "note": "Great turn.",
                    "tag": "strong", "surfaced": True,
                    "direction": "challenge",
                }],
            })
        # The publish continues past the inline save (this session has no
        # user → 400 NO_USER downstream — fine, the save already ran).
        m_lanes.assert_called_once()
        args = m_lanes.call_args.args
        self.assertEqual(args[0], self.SESSION_ID)
        self.assertEqual(args[1], self.SNIP_ID)
        # FE alias folded: direction → direction_label; id stripped.
        self.assertNotIn("id", args[2])
        self.assertEqual(args[2]["direction_label"], "challenge")
        self.assertEqual(args[2]["note"], "Great turn.")

    def test_inline_snippet_not_in_session_404s_before_contract(self):
        session = {"id": self.SESSION_ID, "user_id": "u1"}
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value=session), \
             patch.object(v2.db, "get_snippets_by_session",
                          return_value=[{"id": self.SNIP_ID}]), \
             patch.object(v2, "_apply_willab_publish_contract") as m_contract:
            body, status = self._call({
                "session_id": self.SESSION_ID,
                "notify_client": False,
                "snippets": [{"id": "not-a-known-snippet", "note": "x"}],
            })
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SNIPPET_NOT_FOUND")
        m_contract.assert_not_called()

    def test_absent_snippets_key_is_backward_compatible(self):
        session = {"id": self.SESSION_ID, "user_id": None}
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value=session), \
             patch.object(v2, "_save_coach_snippet_lanes") as m_lanes, \
             patch.object(v2, "_apply_willab_publish_contract",
                          return_value=None), \
             patch.object(v2.db, "record_snippet_publish_annotations",
                          return_value=0), \
             patch.object(v2.db, "v2_update_session_status_unscoped"):
            body, status = self._call({
                "session_id": self.SESSION_ID, "notify_client": False,
            })
        m_lanes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
