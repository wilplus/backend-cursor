"""
STORY    As a signed-out speaker, I want to reopen my own readout with my
         guest pass but never someone else's, and to have a video upload
         refused clearly, so that my recording stays private and the record
         step stays audio-only.
OUTCOME
  O1  My guest pass (or my account, once claimed) opens my readout, with
      its state.
  O2  A bare Take id, or someone else's Take, answers 404 SESSION_NOT_FOUND
      without saying whose it is; a malformed id answers 400.
  O3  A video upload answers 415 AUDIO_ONLY; the mic's own audio/webm passes
      the gate.
PROVES   O1 -> test_the_guest_owner_reads_their_readout
               test_claimed_owner_can_read
               test_state_reflects_lifecycle
         O2 -> test_bare_session_id_is_not_authorization
               test_claimed_by_other_404s_without_leak
               test_bad_uuid_400s
         O3 -> test_a_video_upload_is_refused_as_audio_only
               test_mic_audio_webm_is_NOT_rejected_as_video
WHY      Bug batch 2026-07-13 (BE-1 guest re-read, BE-2 video reject).
"""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import lab_recording as v2_lab_recording
    from services.db import db
    from services.project_ownership import GUEST_OWNER_HEADER, issue_guest_owner
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


_SID = "11111111-1111-4111-8111-111111111111"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class GuestReadoutTests(unittest.TestCase):
    """BE-1 — the canonically-owned readout re-read endpoint."""

    _READOUT = {"snippets": [{"id": "s1", "transcript": "hi",
                              "say_it_stronger": {"already_strong": False,
                                                  "upgrades": []}}]}

    def setUp(self):
        self.app = Flask(__name__)
        self._guest = issue_guest_owner()
        self._session = {"id": _SID, "user_id": None,
                         "owner_principal_id": self._guest.principal_id,
                         "status": "readout_ready"}
        self._p = [
            patch.object(db, "v2_get_session_by_id",
                         lambda sid: self._session),
            patch.object(db, "get_owner_principal",
                         lambda principal_id: {
                             "id": self._guest.principal_id,
                             "user_id": None,
                             "guest_secret_hash": self._guest.secret_hash,
                         } if principal_id == self._guest.principal_id else None),
            patch.object(db, "get_owner_principal_for_user",
                         lambda user_id: {"id": "owner-1", "user_id": user_id}),
            patch("services.lab_recording.build_readout_from_session",
                  lambda sid, **kw: dict(self._READOUT)),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self, session_id=_SID, user_id=None, include_guest=True):
        headers = ({GUEST_OWNER_HEADER: self._guest.token}
                   if include_guest and user_id is None else None)
        with self.app.test_request_context(headers=headers):
            if user_id is not None:
                request.user_id = user_id
            resp, status = v2_lab_recording.v2_guest_get_recording_readout.__wrapped__(session_id)
            return resp.get_json(), status

    def test_the_guest_owner_reads_their_readout(self):
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual((body["session_id"], body["state"], body["readout"]),
                         (_SID, "readout_ready", self._READOUT))

    def test_bare_session_id_is_not_authorization(self):
        body, status = self._call(include_guest=False)
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SESSION_NOT_FOUND")

    def test_claimed_by_other_404s_without_leak(self):
        self._session = {"id": _SID, "user_id": "owner-x",
                         "owner_principal_id": "owner-x"}
        body, status = self._call(user_id=None)          # anonymous caller
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SESSION_NOT_FOUND")

    def test_claimed_owner_can_read(self):
        self._session = {"id": _SID, "user_id": "u1",
                         "owner_principal_id": "owner-1",
                         "status": "readout_ready"}
        body, status = self._call(user_id="u1")
        self.assertEqual(status, 200)
        self.assertEqual(body["readout"], self._READOUT)

    def test_bad_uuid_400s(self):
        _, status = self._call(session_id="not-a-uuid")
        self.assertEqual(status, 400)

    def test_state_reflects_lifecycle(self):
        self._session = {"id": _SID, "user_id": None,
                         "owner_principal_id": self._guest.principal_id,
                         "status": "pending_admin_review"}
        body, _ = self._call()
        self.assertEqual(body["state"], "review_pending")


def _file(name, ctype, body=b"xxxxxxxxxx"):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(body), filename=name,
                       content_type=ctype)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VideoRejectTests(unittest.TestCase):
    """BE-2 — video rejected at the Lab upload; audio/webm still passes."""

    def _post(self, filename, ctype, form=None):
        data = {"audio_file": _file(filename, ctype)}
        if form:
            data.update(form)
        with self.app.test_request_context(
                method="POST", data=data,
                content_type="multipart/form-data"):
            project = SimpleNamespace(
                project_id="project-1", idempotency_key="upload-1",
                duplicate_take=None, principal=SimpleNamespace(id="owner-1"),
            )
            with patch("routes.v2.lab_recording.resolve_take_project",
                       return_value=project):
                resp, status = v2_lab_recording.v2_lab_create_recording.__wrapped__()
            return resp.get_json(), status

    def setUp(self):
        self.app = Flask(__name__)

    def test_a_video_upload_is_refused_as_audio_only(self):
        for filename, ctype in (("talk.mp4", "video/mp4"), ("talk.webm", "video/webm"),
                                ("talk.mov", "application/octet-stream")):
            body, status = self._post(filename, ctype)
            self.assertEqual((status, body["code"]), (415, "AUDIO_ONLY"), filename)

    def test_mic_audio_webm_is_NOT_rejected_as_video(self):
        # the live mic sends audio/webm (.webm) — it must pass the video gate
        # (it fails LATER for a different reason: no topic → 422, never 415).
        body, status = self._post("lab.webm", "audio/webm")
        self.assertNotEqual(status, 415)
        self.assertNotEqual((body or {}).get("code"), "AUDIO_ONLY")


if __name__ == "__main__":
    unittest.main()
