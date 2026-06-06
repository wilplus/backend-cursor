"""willab coach feedback video upload (3b / B.3).

Mirrors the proven afterwards-video handler: store via coach_video_storage,
persist coach_video_ref on the session (the publish contract folds it into
insights_payload — covered in test_coach_publish). Storage + db are stubbed;
the view is invoked via __wrapped__ (auth covered by test_coach_auth).

Run: python3 -m unittest test_coach_video
"""
from __future__ import annotations

import io
import unittest

try:
    from flask import Flask
    from routes import v2_routes as v2
    import services.coach_video_storage as cvs
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    v2 = None
    cvs = None
    _IMPORT_ERROR = e


SID = "11111111-1111-4111-8111-111111111111"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach video tests need app deps: {_IMPORT_ERROR}")
class CoachVideoTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.stored = {}
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {"id": sid})
        self._patch_db("set_session_coach_video_ref", self._capture_ref)
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

    def _capture_ref(self, session_id, ref):
        self.stored["ref"] = ref
        return True

    def _post(self, filename, content=b"video-bytes"):
        data = {"video_file": (io.BytesIO(content), filename)}
        with self.app.test_request_context(
            data=data, content_type="multipart/form-data",
        ):
            return v2.v2_coach_session_video.__wrapped__(SID)

    def test_happy_path_stores_and_sets_ref(self):
        resp, status = self._post("feedback.mp4")
        self.assertEqual(status, 200)
        self.assertEqual(self.stored["key"], f"coach-feedback/{SID}.mp4")
        self.assertEqual(self.stored["ref"], f"https://cdn/coach-feedback/{SID}.mp4")
        self.assertEqual(resp.get_json()["video_ref"], self.stored["ref"])

    def test_bad_extension_415_no_store(self):
        resp, status = self._post("feedback.txt")
        self.assertEqual(status, 415)
        self.assertNotIn("ref", self.stored)

    def test_empty_file_400(self):
        resp, status = self._post("feedback.mp4", content=b"")
        self.assertEqual(status, 400)
        self.assertNotIn("ref", self.stored)

    def test_missing_session_404(self):
        setattr(v2.db, "v2_get_session_by_id", lambda sid: None)
        resp, status = self._post("feedback.mp4")
        self.assertEqual(status, 404)
        self.assertNotIn("ref", self.stored)


if __name__ == "__main__":
    unittest.main()
