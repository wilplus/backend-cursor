"""willab coach feedback video upload (3b / B.3).

Mirrors the proven afterwards-video handler: store via coach_video_storage,
persist coach_video_ref on the session (the publish contract folds it into
canonical feedback publishing — covered in test_coach_publish). Storage + db are stubbed;
the view is invoked via __wrapped__ (auth covered by test_coach_auth).

Run: python3 -m unittest test_coach_video
"""
from __future__ import annotations

import io
import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    import services.coach_video_storage as cvs
    import services.coach_video_capture as cvc
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    request = None
    v2 = None
    cvs = None
    cvc = None
    _IMPORT_ERROR = e


SID = "11111111-1111-4111-8111-111111111111"
COACH = "33333333-3333-4333-8333-333333333333"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach video tests need app deps: {_IMPORT_ERROR}")
class CoachVideoTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.stored = {}
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {"id": sid})
        self._patch_db("set_session_coach_video_ref", self._capture_ref)
        # Subsystem V corpus lane. Stubbed so the capture path actually RUNS
        # here: it is wrapped in a bare `except → logger.warning(non-fatal)` in
        # the route, so an unstubbed db turns a real breakage into a silent
        # pass. self.assets is what the corpus would have received.
        self.assets = []
        self._patch_db("get_current_coach_video_asset",
                       lambda sid, ct, snip: (self.assets[-1] if self.assets
                                              else None))
        self._patch_db("insert_coach_video_asset", self._capture_asset)
        self._patch_db("supersede_coach_video_asset",
                       lambda prior_id, new_id: self.superseded.append(
                           (prior_id, new_id)))
        self.superseded = []
        # Transcription spawns a daemon thread that hits ffmpeg + Whisper.
        # Keep the test hermetic.
        self._orig_spawn = cvc._spawn_transcription
        cvc._spawn_transcription = lambda *a, **k: None
        self._orig_put = cvs.put_coach_object_bytes
        self._orig_url = cvs.coach_media_public_url
        cvs.put_coach_object_bytes = self._fake_put
        cvs.coach_media_public_url = lambda key: f"https://cdn/{key}"

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)
        cvs.put_coach_object_bytes = self._orig_put
        cvs.coach_media_public_url = self._orig_url
        cvc._spawn_transcription = self._orig_spawn

    def _capture_asset(self, row):
        created = {"id": f"asset-{len(self.assets) + 1}", **row}
        self.assets.append(created)
        return created

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
            # The real route is @require_admin_or_coach, which wraps
            # require_auth and sets request.user_id before the handler runs.
            # Calling __wrapped__ skips that, so set it here — without it the
            # Subsystem V corpus capture below raises AttributeError and is
            # swallowed as "non-fatal", hiding whether capture works at all.
            request.user_id = COACH
            return v2.v2_coach_session_video.__wrapped__(SID)

    def test_happy_path_stores_and_sets_ref(self):
        resp, status = self._post("feedback.mp4")
        self.assertEqual(status, 200)
        key = self.stored["key"]
        self.assertTrue(key.startswith(f"coach-feedback/{SID}/"), key)
        self.assertTrue(key.endswith(".mp4"), key)
        self.assertEqual(self.stored["ref"], f"https://cdn/{key}")
        self.assertEqual(resp.get_json()["video_ref"], self.stored["ref"])

    def test_take_is_not_captured_into_a_training_corpus(self):
        """Phase 1 stores product video without a hidden learning write."""
        self._post("feedback.mp4")
        self.assertEqual(self.assets, [])

    def test_re_record_does_not_create_a_training_preference(self):
        self._post("feedback.mp4")
        self._post("feedback.mp4")
        self.assertEqual(self.assets, [])
        self.assertEqual(self.superseded, [])

    def test_re_record_does_not_overwrite_the_prior_take(self):
        """Subsystem V: the storage key carries a per-upload uuid so a coach
        re-recording their feedback ADDS a take rather than destroying the
        previous one — the prior take is training/preference data. Only the
        user-facing ref is repointed to the newest."""
        self._post("feedback.mp4")
        first_key, first_ref = self.stored["key"], self.stored["ref"]
        self._post("feedback.mp4")
        self.assertNotEqual(self.stored["key"], first_key)
        self.assertNotEqual(self.stored["ref"], first_ref)

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
