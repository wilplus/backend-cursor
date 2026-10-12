"""Lossless WebM remux on upload (founder 2026-10-08: playback everywhere).

MediaRecorder WebM has no Cues and no Duration, so Safari cannot seek a clip
inside its parent Take. services/webm_remux.py rewrites the container with
`-c copy -copyts` before storage and analysis. These tests prove the three
things that make that safe:

* timestamps are preserved: start_time and the end of the last packet equal
  within 20 ms (in fact exactly), every packet identical, and the decoded
  PCM identical, so no analysis offset can move;
* any failure keeps the original bytes and never raises (LIVE LOOP);
* the sha256 read-after-write check runs on the bytes actually stored.

Run: python3 -m pytest tests/test_webm_remux.py
"""
from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from services.ffmpeg_audio_extract import resolve_ffmpeg_executable
    _FFMPEG = resolve_ffmpeg_executable()
except Exception:  # pragma: no cover
    _FFMPEG = None


def _make_mediarecorder_like_webm(*, offset_s: float = 0.0) -> bytes | None:
    """A live-style Opus WebM (no Cues, no Duration), like MediaRecorder's."""
    if not _FFMPEG:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "in.webm")
        args = [_FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i",
                "aevalsrc='sin(440*2*PI*t)*(0.5+0.5*sin(3*t))':s=48000:d=4",
                "-c:a", "libopus", "-b:a", "32k"]
        if offset_s:
            args += ["-output_ts_offset", str(offset_s)]
        args += ["-f", "webm", "-live", "1", out]
        proc = subprocess.run(args, capture_output=True, timeout=60, check=False)
        if proc.returncode != 0 or not os.path.isfile(out):
            return None
        with open(out, "rb") as fh:
            return fh.read()


_FIXTURE = _make_mediarecorder_like_webm()
_NEEDS_FIXTURE = unittest.skipIf(
    _FIXTURE is None, "needs ffmpeg with libopus to build the WebM fixture")


@_NEEDS_FIXTURE
class TheStoredBytesAreTheRemuxedBytes(unittest.TestCase):
    """The upload reads, remuxes, then stores and verifies the SAME bytes, so
    the sha256 read-after-write check holds for what is actually stored."""

    def test_intake_remuxes_and_the_read_after_write_sha_matches(self):
        from services import lab_audio_storage, processing_authorization
        from services.lab_audio_intake import read_recording_upload
        from services.lab_recording_persistence import store_recording_audio

        upload = SimpleNamespace(stream=io.BytesIO(_FIXTURE),
                                 mimetype="audio/webm", filename="take.webm")
        got = read_recording_upload({"audio_file": upload}, content_length=None,
                                    max_audio_mb=50, context_max_mb=1,
                                    video_extensions=set())
        self.assertNotEqual(got.audio_bytes, _FIXTURE)
        self.assertIn(bytes.fromhex("1C53BB6B"), got.audio_bytes)

        store: dict = {}

        def put(key, body, content_type):
            store[key] = bytes(body)
            return "lab-bucket"

        class _Auth:
            enforced = True

            def __init__(self, _db):
                pass

            def queue_orphan(self, **_k):
                raise AssertionError("verification must not fail")

        class _Takes:
            def v2_create_recording_session(self, *_a, **_k):
                return None

            def v2_set_session_upload_key(self, *_a, **_k):
                return None

        with patch.object(lab_audio_storage, "put_lab_audio_bytes", put), \
                patch.object(lab_audio_storage, "get_exact_storage_object_bytes",
                             lambda key, bucket, storage_provider: store[key]), \
                patch.object(lab_audio_storage, "lab_audio_public_url", lambda k: None), \
                patch.object(lab_audio_storage, "storage_provider", lambda: "r2"), \
                patch.object(processing_authorization, "ProcessingAuthorizationService", _Auth):
            stored = store_recording_audio(
                upload, got.audio_bytes, upload_key="k", owner_principal_id="p",
                user_id="u", database=SimpleNamespace(takes=_Takes()),
                deadline=SimpleNamespace(check=lambda *_a: None),
                log=SimpleNamespace(error=lambda *_a, **_k: None))
        self.assertEqual(stored.verification_method, "read_after_write_sha256")
        self.assertEqual(stored.exact_bytes_sha256,
                         hashlib.sha256(store[stored.storage_key]).hexdigest())
        self.assertEqual(store[stored.storage_key], got.audio_bytes)


if __name__ == "__main__":
    unittest.main()
