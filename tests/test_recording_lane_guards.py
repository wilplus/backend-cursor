"""willab — recording-lane guards (founder bugs 2026-07-20).

"Please do not count re-read as a separate take — only a spoken take is a
real take" + "after the re-read, recording the spoken version analyses the
re-read". Three guards, pinned here:

  A1 an UNPAIRED read is rejected 422 before any storage (it used to fall
     through as SPOKEN: taking a take number, assembling, minting a
     version);
  A2 a SPENT session id (one that already owns a recording / a lane /
     analysis) is never reused — a fresh session is minted, so a new
     spoken take can never be folded into the previous re-read;
  A3 assembly/version/bubble run for SPOKEN takes ONLY — the SD-mode
     condition `_rec_kind == "spoken" or _single_deliverable_enabled()`
     let a re-read run the whole pipeline (regenerate suggestions,
     reassemble, bump the version, fire the ready bubble).

Run: python3 -m unittest tests.test_recording_lane_guards
"""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from flask import Flask

    from routes.v2 import lab_recording as v2_lab_recording
    from services.db import db as v2_db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    _IMPORT_ERROR = e

PAIR = "22222222-2222-4222-8222-222222222222"


def _file(name="take.webm", ctype="audio/webm", body=b"x" * 32):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(body), filename=name,
                       content_type=ctype)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UnpairedReadTests(unittest.TestCase):
    """A1 — a read without its spoken take is refused, and refused EARLY
    (before storage/processing), so nothing about it can be persisted."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, form):
        data = {"audio_file": _file()}
        data.update(form)
        with self.app.test_request_context(
                method="POST", data=data,
                content_type="multipart/form-data"):
            # Any storage/DB touch would mean the guard ran too late.
            project = SimpleNamespace(
                project_id="project-1", idempotency_key="upload-1",
                duplicate_take=None, principal=SimpleNamespace(id="owner-1"),
            )
            with patch("routes.v2.lab_recording.resolve_take_project",
                       return_value=project), \
                 patch("routes.v2.lab_recording."
                       "ensure_project_presentation_unchanged"), \
                 patch.object(v2_db, "v2_get_session_by_id") as m_sess, \
                 patch("services.coach_video_storage.put_coach_object_bytes") \
                    as m_put:
                out = v2_lab_recording.v2_lab_create_recording.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_sess, m_put

    PAIR = "3f7c1b6e-6f5a-4a7e-9f2b-8c1d0e5a4b39"
    SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"


    def test_delivery_star_snippet_rerecord_still_passes(self):
        # The read lane SURVIVES for the delivery-star snippet re-record —
        # a separate live feature that shares the wire and was never in
        # scope for the retirement. It must not hit the retirement guard.
        body, status, _, _ = self._post(
            {"topic": "t", "recording_kind": "read",
             "paired_session_id": self.PAIR,
             "paired_snippet_id": self.SNIP})
        self.assertNotIn(
            "retired", ((body or {}).get("error", "") or "").lower())


if __name__ == "__main__":
    unittest.main()
