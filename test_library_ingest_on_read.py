"""Wiring test — the published-readout READ ingests the strong-sides library.

§7: ingest_session_library is the SOLE library-populate trigger, fired ON
READ from GET /v2/user/sessions/<id>/readout when the session is published.
The function + its store were built and unit-tested but left UNWIRED (the
library stayed permanently empty); this guards the wire so it can't silently
regress to dead code again.

Run: python3 -m unittest test_library_ingest_on_read
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


@unittest.skipIf(
    _IMPORT_ERROR is not None,
    f"library-ingest wiring test requires full app deps: {_IMPORT_ERROR}",
)
class LibraryIngestOnReadTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.user_id = "user-lib-1"
        self.sid = "11111111-1111-1111-1111-111111111111"
        self.upserts: list = []          # rows captured at the store boundary
        self.originals = {}
        self._cur_session = None

        published = {
            "id": self.sid,
            "user_id": self.user_id,
            "results_published_at": "2026-06-06T00:00:00+00:00",
            "status": "completed",
            "insights_payload": {
                "overall_message": None,
                "snippet_notes": [
                    {"snippet_id": "a", "note": "Strong open.",
                     "tag": "strong", "when": None, "examples": []},
                ],
            },
        }
        prepub = {
            "id": self.sid,
            "user_id": self.user_id,
            "results_published_at": None,
            "status": "pending_admin_review",
            "insights_payload": None,
        }
        self._sessions = {"pub": published, "pre": prepub}
        self._snippets = [{
            "id": "a", "transcript": "hello there", "metrics": {},
            "start_offset_ms": 0, "duration_ms": 8000,
            "audio_segment_path": "p/a.wav",
        }]

        self._patch("v2_get_session_by_id", lambda sid: self._cur_session)
        self._patch("get_snippets_by_session", lambda sid: list(self._snippets))
        self._patch(
            "upsert_strong_sides_library",
            lambda rows: (self.upserts.extend(rows) or len(rows)),
        )

    def tearDown(self):
        for target, attr, original in reversed(self.originals.values()):
            setattr(target, attr, original)

    def _patch(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr))
        setattr(v2.db, attr, fn)

    def _read(self):
        ctx = self.app.test_request_context(
            f"/v2/user/sessions/{self.sid}/readout", method="GET",
        )
        with ctx:
            v2.request.user_id = self.user_id
            resp, status = v2.v2_user_get_session_readout.__wrapped__(self.sid)
            return status, resp.get_json()

    def test_published_read_ingests_library(self):
        self._cur_session = self._sessions["pub"]
        status, body = self._read()
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "insights_ready")
        # The wire fired: the coach-tagged note was ingested on read.
        self.assertTrue(self.upserts, "published read must ingest the library")
        self.assertEqual(self.upserts[0]["tag"], "strong")
        self.assertEqual(self.upserts[0]["snippet_id"], "a")
        self.assertEqual(self.upserts[0]["user_id"], self.user_id)

    def test_prepublish_read_does_not_ingest(self):
        self._cur_session = self._sessions["pre"]
        status, body = self._read()
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "review_pending")
        self.assertEqual(self.upserts, [], "pre-publish read must NOT ingest")
        # And the raw snippets still serve pre-publish (verify #3), with
        # no coach block folded.
        self.assertEqual(len(body["readout"]["snippets"]), 1)
        self.assertNotIn("coach", body["readout"]["snippets"][0])


if __name__ == "__main__":
    unittest.main()
