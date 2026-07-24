"""GET /v2/talks/<talk_id>/ideal-text — ROUTE-level test of the
coach_finalized content gate. (The 402 paywall that used to compose with this
gate was retired with the single-deliverable flag — the ideal text is free
now.) Only the service function was covered before this file — see
test_ideal_text_report.py for the pure build_ideal_text_report mapping tests,
and test_best_presentation.py's CoachFinalizedGateTests for the gate itself.

Run: python3 -m unittest test_ideal_text_route
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


def _sess(sid="s1"):
    return {
        "id": sid, "user_id": "u1", "take_index": 1,
        "intake_context": {
            "topic": "My talk",
            "slides": [{"title": "Slide 1", "body": "p"}],
            "slide_advances": [{"index": 0, "t_ms": 0}],
        },
    }


def _snip(sid):
    return {"id": sid, "start_offset_ms": 0, "duration_ms": 1000,
            "transcript": "a line", "storage_path": f"s3://{sid}",
            "metrics": {"overall_score": 0.5}}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class IdealTextRouteCompositionTests(unittest.TestCase):
    """The coach_finalized content gate (services.best_presentation): the
    route returns 200 with an empty idealText until the coach has corrected
    EVERY slide, then serves the real corrected text. (The 402 paywall that
    used to gate this route was retired with the single-deliverable flag.)"""

    def setUp(self):
        self.app = Flask(__name__)
        sessions = [_sess(f"s{i}") for i in range(3)]
        snips = {f"s{i}": [_snip(f"c{i}")] for i in range(3)}
        self._p = [
            patch.object(v2, "_arc_owned_by_caller",
                        lambda arc_id: (True, sessions)),
            patch.object(v2, "is_admin", lambda uid: False),
            patch.object(v2, "is_coach", lambda uid: False),
            patch.object(v2.db, "get_arc_sessions", lambda arc_id: sessions),
            patch.object(v2.db, "get_snippets_by_session",
                        lambda sid: snips.get(sid, [])),
            patch.object(v2.db, "get_training_labels", lambda sid: []),
            patch.object(v2.db, "get_best_presentation_edits",
                        lambda arc_id: {}),
        ]
        for p in self._p:
            p.start()
        self._coach_edits = {}
        self._purchase = None
        _edits_patch = patch.object(
            v2.db, "get_coach_best_presentation_edits",
            lambda arc_id: dict(self._coach_edits),
        )
        _purchase_patch = patch.object(
            v2.db, "get_arc_purchase", lambda arc_id: self._purchase,
        )
        self._p += [_edits_patch, _purchase_patch]
        _edits_patch.start()
        _purchase_patch.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _call(self, talk_id="a1"):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_talk_ideal_text.__wrapped__(talk_id)
            return resp.get_json(), status

    def test_paid_but_not_finalized_returns_200_with_empty_ideal_text(self):
        self._purchase = {"arc_id": "a1", "user_id": "u1"}
        self._coach_edits = {}  # coach hasn't corrected anything yet
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertFalse(body["coachFinalized"])
        for s in body["slides"]:
            self.assertEqual(s["idealText"], "")

    def test_paid_and_finalized_returns_real_ideal_text(self):
        self._purchase = {"arc_id": "a1", "user_id": "u1"}
        self._coach_edits = {0: "coach's corrected line"}
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertTrue(body["coachFinalized"])
        self.assertEqual(body["slides"][0]["idealText"],
                         "coach's corrected line")

    def test_not_owner_404s(self):
        with patch.object(v2, "_arc_owned_by_caller",
                          lambda arc_id: (False, [])):
            body, status = self._call()
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PencilEditRichFormatTests(unittest.TestCase):
    """Backlog 1.7 (B6): the pencil-edit route passes the marker subset
    (**b** *i* __u__ ==hl==) through as plain text and strips raw HTML."""

    def setUp(self):
        self.app = Flask(__name__)
        self._saved = {}

        def _upsert(arc_id, index, text, user_id=None):
            self._saved["text"] = text
            return True

        self._p = [
            patch.object(v2, "_arc_owned_by_caller", lambda a: (True, [])),
            patch.object(v2.db, "upsert_best_presentation_edit", _upsert),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _call(self, text):
        with self.app.test_request_context(json={"text": text}):
            request.user_id = "u1"
            resp, status = v2.v2_explore_arc_edit_slide.__wrapped__("a1", 0)
            return resp.get_json(), status

    def test_marker_subset_passes_through(self):
        _, status = self._call("**bold** and *italic* and __under__ ==hl==")
        self.assertEqual(status, 200)
        self.assertEqual(self._saved["text"],
                         "**bold** and *italic* and __under__ ==hl==")

    def test_html_tags_stripped(self):
        _, status = self._call('<script>x()</script>**keep** <b>drop tags</b>')
        self.assertEqual(status, 200)
        self.assertNotIn("<", self._saved["text"])
        self.assertIn("**keep**", self._saved["text"])
        self.assertIn("drop tags", self._saved["text"])  # inner text kept

    def test_tags_only_body_is_400(self):
        body, status = self._call("<b></b><i></i>")
        self.assertEqual(status, 400)

    def test_tags_cannot_smuggle_past_length_cap(self):
        # Post-strip length is what the cap checks.
        _, status = self._call("<b>" + "x" * 2000 + "</b>")
        self.assertEqual(status, 200)  # exactly at cap after strip
        _, status = self._call("<b>" + "x" * 2001 + "</b>")
        self.assertEqual(status, 400)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ArcProgressCoachFinalizedTests(unittest.TestCase):
    """Backlog 4.2 (B8): the cheap progress poll carries coach_finalized so
    the FE can show "waiting for the coach to assemble" at 3/3."""

    def setUp(self):
        self.app = Flask(__name__)
        deck = {"slides": [{"title": "S1", "body": ""},
                           {"title": "S2", "body": ""}]}
        self._sessions = [
            {"id": f"s{i}", "user_id": "u1", "take_index": i + 1,
             "intake_context": dict(deck)}
            for i in range(3)
        ]
        self._coach_edits = {}
        self._p = [
            # 2026-07-16: the guest-capable progress route reads
            # db.get_arc_sessions directly (no _arc_owned_by_caller).
            patch.object(v2.db, "get_arc_sessions",
                         lambda arc_id: list(self._sessions)),
            patch.object(v2.db, "get_coach_best_presentation_edits",
                         lambda arc_id: dict(self._coach_edits)),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_explore_arc_progress.__wrapped__("a1")
            return resp.get_json(), status

    def test_not_finalized_until_every_slide_corrected(self):
        self._coach_edits = {0: "corrected one"}  # 1 of 2 slides
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["takes_done"], 3)
        self.assertFalse(body["coach_finalized"])

    def test_finalized_when_all_slides_corrected(self):
        self._coach_edits = {0: "one", 1: "two"}
        body, _ = self._call()
        self.assertTrue(body["coach_finalized"])

    def test_deckless_arc_never_finalized(self):
        for s in self._sessions:
            s["intake_context"] = {"topic": "t"}
        self._coach_edits = {0: "x"}
        body, _ = self._call()
        self.assertFalse(body["coach_finalized"])


if __name__ == "__main__":
    unittest.main()
