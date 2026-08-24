"""Guest readout re-read + video-upload reject (bug batch 2026-07-13).

BE-1: GET /v2/lab/recordings/<id>/readout — the unauth twin of the authed
      re-read, so a signed-out user can poll for the async Say-It-Stronger
      cards and re-open their recording without hitting the 401 → "couldn't
      load these insights" screen. The signed Guest ID is required; a bare
      session UUID is never authorization.
BE-2: /v2/lab/recordings rejects a VIDEO upload with 415 AUDIO_ONLY — while
      the mic's own audio/webm (.webm) still passes.

Flask-route classes skip locally, run in CI (the known gotcha).

Run: python3 -m unittest test_guest_readout_video
"""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    from services.project_ownership import GUEST_OWNER_HEADER, issue_guest_owner
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
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
            patch.object(v2.db, "v2_get_session_by_id",
                         lambda sid: self._session),
            patch.object(v2.db, "get_owner_principal",
                         lambda principal_id: {
                             "id": self._guest.principal_id,
                             "user_id": None,
                             "guest_secret_hash": self._guest.secret_hash,
                         } if principal_id == self._guest.principal_id else None),
            patch.object(v2.db, "get_owner_principal_for_user",
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
            resp, status = v2.v2_guest_get_recording_readout.__wrapped__(session_id)
            return resp.get_json(), status

    def test_guest_owned_session_served_with_verified_guest_principal(self):
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["session_id"], _SID)
        # the async synonym cards ride through so the FE can poll for them
        self.assertIn("say_it_stronger", body["readout"]["snippets"][0])

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

    def test_unknown_session_404s(self):
        self._session = None
        _, status = self._call()
        self.assertEqual(status, 404)

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
                resp, status = v2.v2_lab_create_recording.__wrapped__()
            return resp.get_json(), status

    def setUp(self):
        self.app = Flask(__name__)

    def test_video_mimetype_rejected(self):
        body, status = self._post("clip.mp4", "video/mp4")
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], "AUDIO_ONLY")

    def test_video_extension_rejected_even_if_mislabeled(self):
        # extension is video even though the client lied about the mimetype
        body, status = self._post("talk.mov", "application/octet-stream")
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], "AUDIO_ONLY")

    def test_video_webm_rejected_by_mimetype(self):
        body, status = self._post("clip.webm", "video/webm")
        self.assertEqual(status, 415)

    def test_mic_audio_webm_is_NOT_rejected_as_video(self):
        # the live mic sends audio/webm (.webm) — it must pass the video gate
        # (it fails LATER for a different reason: no topic → 422, never 415).
        body, status = self._post("lab.webm", "audio/webm")
        self.assertNotEqual(status, 415)
        self.assertNotEqual((body or {}).get("code"), "AUDIO_ONLY")

    def test_plain_audio_files_pass_the_video_gate(self):
        for name, ct in (("take.m4a", "audio/mp4"),
                         ("take.mp3", "audio/mpeg"),
                         ("take.wav", "audio/wav")):
            body, status = self._post(name, ct)
            self.assertNotEqual(status, 415, f"{name} wrongly rejected")
            self.assertNotEqual((body or {}).get("code"), "AUDIO_ONLY")


if __name__ == "__main__":
    unittest.main()
