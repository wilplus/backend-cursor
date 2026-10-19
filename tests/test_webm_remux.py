"""
STORY    As a speaker, I want my recording made seekable without changing its
         timing, and kept as-is if that fails, so that playback works
         everywhere and my Take is never lost. (Critical path: record.)
OUTCOME
  O1  The remuxed file carries a seek index and exactly the same packets and
      timestamps as the recording (even one not starting at zero), so no
      stored offset moves.
  O2  Any remux failure (ffmpeg error or timeout) keeps the original bytes
      and never raises, so the Take still goes on (Never-3: the loop is never
      broken).
  O3  The bytes stored are the remuxed bytes, and the read-after-write
      checksum is taken on what is actually stored.
PROVES   O1 -> test_timestamps_and_packets_are_preserved
         O2 -> test_any_remux_failure_keeps_the_original_bytes
         O3 -> test_intake_remuxes_and_the_read_after_write_sha_matches
WHY      Founder 2026-10-08: Safari could not seek a clip inside its Take
         (MediaRecorder WebM has no Cues and no Duration).
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

from services import webm_remux

try:
    from services.ffmpeg_audio_extract import resolve_ffmpeg_executable
    _FFMPEG = resolve_ffmpeg_executable()
except Exception:  # pragma: no cover
    _FFMPEG = None

_CUES = bytes.fromhex("1C53BB6B")


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


class TheRemuxNeverLosesATake(unittest.TestCase):

    @_NEEDS_FIXTURE
    def test_timestamps_and_packets_are_preserved(self):
        original = _make_mediarecorder_like_webm(offset_s=1.5)
        self.assertIsNotNone(original)
        remuxed = webm_remux.remux_webm_for_seeking(original)
        self.assertNotEqual(remuxed, original)
        self.assertIn(_CUES, remuxed)
        self.assertNotIn(_CUES, original)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, data in (("a.webm", original), ("b.webm", remuxed)):
                paths.append(os.path.join(tmp, name))
                with open(paths[-1], "wb") as fh:
                    fh.write(data)
            before = webm_remux.packet_lines(_FFMPEG, paths[0], 30)
            after = webm_remux.packet_lines(_FFMPEG, paths[1], 30)
        self.assertTrue(before)
        self.assertEqual(before, after)

    def test_any_remux_failure_keeps_the_original_bytes(self):
        original = _FIXTURE or (b"\x1a\x45\xdf\xa3\x9f\x42\x82\x84webm" + b"\x00" * 512)
        failed = SimpleNamespace(returncode=1, stdout=b"", stderr=b"broken")
        timed_out = subprocess.TimeoutExpired("ffmpeg", 8)
        for name, run in (("ffmpeg error", lambda *a, **k: failed),
                          ("timeout", _raise(timed_out)),
                          ("crash", _raise(OSError("no such file")))):
            with self.subTest(name), \
                    patch.object(webm_remux, "_ffmpeg", lambda: "ffmpeg"), \
                    patch.object(webm_remux.subprocess, "run", run):
                self.assertIs(webm_remux.remux_webm_for_seeking(original), original)


def _raise(error):
    def run(*_a, **_k):
        raise error
    return run


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
        self.assertIn(_CUES, got.audio_bytes)

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
