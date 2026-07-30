"""willab per-snippet coach BREAKTHROUGH-video upload (Phase 2 of #131).

Mirrors test_coach_video: stores via coach_video_storage, persists the public
URL on the snippet DRAFT (coach_snippet_drafts.breakthrough_video_ref) via
upsert_coach_snippet_draft — the publish contract folds it into insights_payload
(test_insights_payload) and build_readout surfaces it on the readout. Storage +
db stubbed; the view is invoked via __wrapped__ (auth covered elsewhere).

Run: python3 -m unittest test_coach_breakthrough_video
"""
from __future__ import annotations

import io
import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    import services.coach_video_storage as cvs
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    request = None
    v2 = None
    cvs = None
    _IMPORT_ERROR = e


SID = "11111111-1111-4111-8111-111111111111"
SNIP = "22222222-2222-4222-8222-222222222222"
COACH = "33333333-3333-4333-8333-333333333333"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachBreakthroughVideoTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.stored = {}
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {"id": sid})
        self._patch_db("get_snippets_by_session", lambda sid: [{"id": SNIP}])
        self._patch_db("upsert_coach_snippet_draft", self._capture)
        self._orig_put = cvs.put_coach_object_bytes
        self._orig_url = cvs.coach_media_public_url
        cvs.put_coach_object_bytes = self._fake_put
        cvs.coach_media_public_url = lambda key: f"https://cdn/{key}"

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)
        cvs.put_coach_object_bytes = self._orig_put
        cvs.coach_media_public_url = self._orig_url

    def _patch_db(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr, None))
        setattr(v2.db, attr, fn)

    def _fake_put(self, bucket, key, data, content_type):
        self.stored["key"] = key
        self.stored["len"] = len(data)

    def _capture(self, session_id, snippet_id, fields, updated_by=None):
        self.stored["ref"] = fields.get("breakthrough_video_ref")
        self.stored["snip"] = snippet_id
        self.stored["by"] = updated_by
        return {"snippet_id": snippet_id, **fields}

    def _post(self, filename, content=b"video-bytes", snip=SNIP):
        data = {"video_file": (io.BytesIO(content), filename)}
        with self.app.test_request_context(
            data=data, content_type="multipart/form-data",
        ):
            request.user_id = COACH
            return v2.v2_coach_snippet_breakthrough_video.__wrapped__(SID, snip)

    def test_happy_path_stores_and_persists_ref(self):
        resp, status = self._post("clip.mp4")
        self.assertEqual(status, 200)
        key = self.stored["key"]
        # Subsystem V: …/<sid>/<snip>/<uuid>.mp4 — the uuid segment is what
        # keeps a re-record from overwriting the prior take.
        self.assertTrue(
            key.startswith(f"coach-snippet-breakthrough/{SID}/{SNIP}/"), key)
        self.assertTrue(key.endswith(".mp4"), key)
        self.assertEqual(self.stored["ref"], f"https://cdn/{key}")
        self.assertEqual(self.stored["by"], COACH)
        body = resp.get_json()
        self.assertEqual(body["breakthrough_video_ref"], self.stored["ref"])
        self.assertEqual(body["snippet_id"], SNIP)

    def test_response_echoes_persisted_coach_state(self):
        # Founder 2026-07-17: the direction chip un-marked after an upload.
        # The response now carries the authoritative coach_state (both lanes
        # folded) so the FE restores the chips from truth instead of
        # clobbering its local state.
        self._patch_db("get_training_labels",
                       lambda sid: [{"snippet_id": SNIP, "value": "threat"}])
        self._patch_db("get_coach_snippet_drafts",
                       lambda sid: [{"snippet_id": SNIP, "note": "the turn",
                                     "tag": "strong", "surfaced": True,
                                     "breakthrough_video_ref": None}])
        resp, status = self._post("clip.mp4")
        self.assertEqual(status, 200)
        cs = resp.get_json()["coach_state"]
        self.assertEqual(cs["direction_label"], "threat")
        self.assertEqual(cs["note"], "the turn")
        self.assertEqual(cs["tag"], "strong")
        self.assertTrue(cs["surfaced"])

    def test_bad_extension_415_no_store(self):
        _, status = self._post("clip.txt")
        self.assertEqual(status, 415)
        self.assertNotIn("ref", self.stored)

    def test_empty_file_400(self):
        _, status = self._post("clip.mp4", content=b"")
        self.assertEqual(status, 400)
        self.assertNotIn("ref", self.stored)

    def test_missing_session_404(self):
        setattr(v2.db, "v2_get_session_by_id", lambda sid: None)
        _, status = self._post("clip.mp4")
        self.assertEqual(status, 404)
        self.assertNotIn("ref", self.stored)

    def test_snippet_not_in_session_404(self):
        setattr(v2.db, "get_snippets_by_session",
                lambda sid: [{"id": "99999999-9999-4999-8999-999999999999"}])
        resp, status = self._post("clip.mp4")
        self.assertEqual(status, 404)
        self.assertEqual(resp.get_json()["code"], "SNIPPET_NOT_FOUND")
        self.assertNotIn("ref", self.stored)

    def test_bad_uuid_400(self):
        with self.app.test_request_context(
            data={"video_file": (io.BytesIO(b"x"), "c.mp4")},
            content_type="multipart/form-data",
        ):
            request.user_id = COACH
            _, status = v2.v2_coach_snippet_breakthrough_video.__wrapped__(
                "not-a-uuid", SNIP)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
