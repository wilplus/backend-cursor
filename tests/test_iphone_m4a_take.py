"""
STORY    As a speaker recording in the iPhone app, I want my Take (an m4a the
         phone writes itself, N655, N662) to be heard like a web Take, so that
         it reaches the Ideal Text and the feedback. (Critical path: record.)
OUTCOME
  O1  An iPhone m4a, whose index sits at the END of the file as iOS writes
      it, passes the no-speech gate and decodes in full: before, ffmpeg read
      it from stdin, found nothing, and the gate refused it as "no_audio".
  O2  The upload keeps it as audio: it is not refused as a video, and its
      bytes are stored as sent (the WebM remux leaves an m4a alone).
  O3  The same speech gate accepts a quiet but voiced native Take; turning
      phone-call gain processing off must not turn a voice into dead air.
PROVES   O1 -> test_an_iphone_m4a_passes_the_gate_and_decodes_in_full
         O2 -> test_the_upload_keeps_an_iphone_m4a_as_audio_bytes_unchanged
         O3 -> test_a_quiet_voiced_iphone_take_passes_the_same_gate
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from werkzeug.datastructures import FileStorage

try:
    from services.ffmpeg_audio_extract import resolve_ffmpeg_executable
    _FFMPEG = resolve_ffmpeg_executable()
except Exception:  # pragma: no cover
    _FFMPEG = None

SECONDS = 70


def _iphone_like_m4a(*, seconds: int = SECONDS, level: float = 1.0) -> bytes | None:
    """AAC mono 48 kHz at 64 kbps with the index (moov) after the audio,
    as the iPhone app writes a Take."""
    if not _FFMPEG:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "take.m4a")
        proc = subprocess.run(
            [_FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i",
             ("aevalsrc='sin(220*2*PI*t)*(0.5+0.5*sin(3*t))"
              f"*{level}':s=48000:d={seconds}"),
             "-ac", "1", "-c:a", "aac", "-b:a", "64k", out],
            capture_output=True, timeout=60, check=False)
        if proc.returncode != 0 or not os.path.isfile(out):
            return None
        with open(out, "rb") as fh:
            data = fh.read()
    assert data.find(b"moov") > data.find(b"mdat"), "index must be at the end"
    return data


@unittest.skipUnless(_FFMPEG, "ffmpeg is needed to make an m4a")
class IphoneM4aTake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.take = _iphone_like_m4a()
        if cls.take is None:
            raise unittest.SkipTest("could not encode an m4a here")

    def test_an_iphone_m4a_passes_the_gate_and_decodes_in_full(self):
        from services.audio_metrics import SAMPLE_RATE, decode_audio_to_pcm
        from services.min_content_gate import evaluate_min_content_bytes

        gate = evaluate_min_content_bytes(self.take)
        self.assertTrue(gate["ok"], gate)

        pcm = decode_audio_to_pcm(self.take)
        self.assertIsNotNone(pcm)
        self.assertAlmostEqual(len(pcm) / SAMPLE_RATE, SECONDS, delta=0.5)

    def test_the_upload_keeps_an_iphone_m4a_as_audio_bytes_unchanged(self):
        import io
        from services.lab_audio_intake import read_recording_upload
        from routes.v2.common import _VIDEO_UPLOAD_EXTS

        upload = FileStorage(stream=io.BytesIO(self.take), filename="lab.m4a",
                             content_type="audio/mp4")
        got = read_recording_upload(
            {"audio_file": upload}, content_length=len(self.take),
            max_audio_mb=100, context_max_mb=25,
            video_extensions=_VIDEO_UPLOAD_EXTS)
        self.assertEqual(got.audio_bytes, self.take)

    def test_a_quiet_voiced_iphone_take_passes_the_same_gate(self):
        from services.min_content_gate import evaluate_min_content_bytes

        quiet_voice = _iphone_like_m4a(seconds=6, level=0.004)
        self.assertIsNotNone(quiet_voice)
        self.assertTrue(evaluate_min_content_bytes(quiet_voice)["ok"])


if __name__ == "__main__":
    unittest.main()
