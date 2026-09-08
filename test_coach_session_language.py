"""Coach confirmation for historical recordings with missing language."""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = error


SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach language tests need app deps: {_IMPORT_ERROR}")
class CoachSessionLanguageTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {
            "id": sid,
            "recording_1_id": RID,
            "intake_context": {},
        })
        self._patch_db("get_recording", lambda rid: {
            "id": rid,
            "transcription_language": None,
        })
        self._patch_db(
            "set_recording_transcription_language_if_missing",
            lambda rid, language: language,
        )

    def tearDown(self):
        for target, attr, original in self.originals.values():
            setattr(target, attr, original)

    def _patch_db(self, attr, fn):
        self.originals[attr] = (v2.db, attr, getattr(v2.db, attr, None))
        setattr(v2.db, attr, fn)

    def _put(self, body):
        with self.app.test_request_context(json=body):
            request.user_id = "coach-1"
            response, status = v2.v2_coach_confirm_session_language.__wrapped__(SID)
            return status, response.get_json()

    def test_confirms_missing_language(self):
        status, body = self._put({"language": "en"})
        self.assertEqual(status, 200)
        self.assertEqual(body["language"], "en")
        self.assertFalse(body["replayed"])

    def test_exact_existing_language_replays(self):
        self._patch_db("get_recording", lambda rid: {
            "id": rid,
            "transcription_language": "English",
        })
        status, body = self._put({"language": "en"})
        self.assertEqual(status, 200)
        self.assertTrue(body["replayed"])

    def test_competing_existing_language_fails_closed(self):
        self._patch_db("get_recording", lambda rid: {
            "id": rid,
            "transcription_language": "pl",
        })
        status, body = self._put({"language": "en"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "CLIP_LANGUAGE_ALREADY_SET")
        self.assertEqual(body["language"], "pl")

    def test_rejects_invalid_language(self):
        status, body = self._put({"language": "english-ish"})
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "INVALID_LANGUAGE")

    def test_requires_canonical_recording(self):
        self._patch_db("get_recording", lambda rid: None)
        status, body = self._put({"language": "en"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "RECORDING_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
