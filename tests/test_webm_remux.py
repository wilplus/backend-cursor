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
import re
import shutil
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


def _probe(data: bytes) -> tuple[float, float]:
    """(start_time, end of the last packet) in seconds. ffprobe when it is
    installed beside ffmpeg (prod's apt ffmpeg has it); otherwise ffmpeg's own
    header line plus its packet list, which read the same container fields."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.webm")
        with open(path, "wb") as fh:
            fh.write(data)
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            start = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=start_time",
                 "-of", "csv=p=0", path], capture_output=True, text=True,
                timeout=30, check=True).stdout.strip().splitlines()[0]
            packets = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "packet=pts_time,duration_time",
                 "-of", "csv=p=0", path], capture_output=True, text=True,
                timeout=30, check=True).stdout.strip().splitlines()
            pts, dur = packets[-1].split(",")[:2]
            return float(start), float(pts) + float(dur)
        info = subprocess.run([_FFMPEG, "-hide_banner", "-i", path],
                              capture_output=True, text=True, timeout=30).stderr
        start = float(re.search(r"start: (-?[0-9.]+)", info).group(1))
        lines = webm_remux.packet_lines(_FFMPEG, path, 30)
        last = [c.strip() for c in lines[-1].split(",")]
        # framecrc: stream, dts, pts, duration, size, crc — WebM's 1/1000 tb.
        return start, (int(last[2]) + int(last[3])) / 1000.0


def _pcm(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.webm")
        with open(path, "wb") as fh:
            fh.write(data)
        return subprocess.run(
            [_FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path,
             "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
            capture_output=True, timeout=60, check=True).stdout


_FIXTURE = _make_mediarecorder_like_webm()
_NEEDS_FIXTURE = unittest.skipIf(
    _FIXTURE is None, "needs ffmpeg with libopus to build the WebM fixture")


@_NEEDS_FIXTURE
class TheRemuxPreservesTheTimeline(unittest.TestCase):

    def test_the_fixture_is_like_mediarecorder_no_cues_no_duration(self):
        self.assertNotIn(bytes.fromhex("1C53BB6B"), _FIXTURE)   # Cues
        self.assertNotIn(bytes.fromhex("4489"), _FIXTURE[:4096])  # Duration

    def test_the_remux_writes_cues_and_a_duration(self):
        out = webm_remux.remux_webm_for_seeking(_FIXTURE)
        self.assertNotEqual(out, _FIXTURE)
        self.assertIn(bytes.fromhex("1C53BB6B"), out)
        self.assertIn(bytes.fromhex("4489"), out)

    def test_start_time_and_duration_are_preserved_within_20_ms(self):
        out = webm_remux.remux_webm_for_seeking(_FIXTURE)
        start_in, end_in = _probe(_FIXTURE)
        start_out, end_out = _probe(out)
        self.assertAlmostEqual(start_in, start_out, delta=0.020)
        self.assertAlmostEqual(end_in - start_in, end_out - start_out, delta=0.020)
        # The Opus codec delay puts the first packet before 0. A plain
        # `-c copy` would re-base it to 0 and shift every offset; -copyts
        # keeps it.
        self.assertLess(start_in, 0.0)

    def test_a_non_zero_start_is_kept(self):
        shifted = _make_mediarecorder_like_webm(offset_s=1.5)
        if shifted is None:
            self.skipTest("ffmpeg could not build the shifted fixture")
        out = webm_remux.remux_webm_for_seeking(shifted)
        self.assertNotEqual(out, shifted)
        self.assertAlmostEqual(_probe(shifted)[0], _probe(out)[0], delta=0.020)

    def test_every_packet_and_the_decoded_audio_are_identical(self):
        out = webm_remux.remux_webm_for_seeking(_FIXTURE)
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a.webm"), os.path.join(tmp, "b.webm")
            open(a, "wb").write(_FIXTURE)
            open(b, "wb").write(out)
            self.assertEqual(webm_remux.packet_lines(_FFMPEG, a, 30),
                             webm_remux.packet_lines(_FFMPEG, b, 30))
        self.assertEqual(_pcm(_FIXTURE), _pcm(out))


class TheRemuxNeverBlocksATake(unittest.TestCase):

    def test_off_returns_the_original(self):
        data = _FIXTURE or b"\x1a\x45\xdf\xa3" + b"\x00" * 10 + b"webm" + b"\x00" * 2000
        with patch("config.Config.WEBM_REMUX_ON_UPLOAD", False):
            self.assertIs(webm_remux.remux_webm_for_seeking(data), data)

    def test_not_webm_is_untouched(self):
        for data in (b"RIFF....WAVEfmt " + b"\x00" * 2000,
                     b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 2000, b""):
            self.assertIs(webm_remux.remux_webm_for_seeking(data), data)

    def test_no_ffmpeg_returns_the_original(self):
        data = b"\x1a\x45\xdf\xa3" + b"\x00" * 10 + b"webm" + b"\x00" * 2000
        with patch.object(webm_remux, "_ffmpeg", lambda: None):
            self.assertIs(webm_remux.remux_webm_for_seeking(data), data)

    @unittest.skipIf(not _FFMPEG, "needs ffmpeg")
    def test_a_broken_file_returns_the_original(self):
        data = b"\x1a\x45\xdf\xa3" + b"\x00" * 10 + b"webm" + os.urandom(4000)
        self.assertIs(webm_remux.remux_webm_for_seeking(data), data)

    @_NEEDS_FIXTURE
    def test_a_timeout_returns_the_original(self):
        def slow(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)
        with patch.object(webm_remux.subprocess, "run", slow):
            self.assertIs(webm_remux.remux_webm_for_seeking(_FIXTURE), _FIXTURE)

    @_NEEDS_FIXTURE
    def test_any_packet_difference_returns_the_original(self):
        calls = {"n": 0}
        real = webm_remux.packet_lines

        def differs(exe, path, timeout):
            calls["n"] += 1
            lines = real(exe, path, timeout)
            return lines if calls["n"] == 1 else lines[:-1]
        with patch.object(webm_remux, "packet_lines", differs):
            self.assertIs(webm_remux.remux_webm_for_seeking(_FIXTURE), _FIXTURE)

    def test_an_unexpected_error_returns_the_original(self):
        data = b"\x1a\x45\xdf\xa3" + b"\x00" * 10 + b"webm" + b"\x00" * 2000
        with patch.object(webm_remux, "_ffmpeg", lambda: "/bin/ffmpeg"), \
                patch.object(webm_remux, "_remux", side_effect=RuntimeError("x")):
            self.assertIs(webm_remux.remux_webm_for_seeking(data), data)


@_NEEDS_FIXTURE
class TheStoredBytesAreTheRemuxedBytes(unittest.TestCase):
    """The upload reads, remuxes, then stores and verifies the SAME bytes, so
    the sha256 read-after-write check holds for what is actually stored."""

    def test_intake_remuxes_and_the_read_after_write_sha_matches(self):
        from services.lab_audio_intake import read_recording_upload
        from services import lab_audio_storage
        from services import processing_authorization
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
