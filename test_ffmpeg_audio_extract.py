import unittest

try:
    from services import ffmpeg_audio_extract as ffmpeg_extract
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    ffmpeg_extract = None
    _IMPORT_ERROR = import_err


class _ProcResult:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


@unittest.skipIf(_IMPORT_ERROR is not None, f"ffmpeg extract tests require app deps: {_IMPORT_ERROR}")
class FfmpegAudioExtractTests(unittest.TestCase):
    def setUp(self):
        self._orig_run = ffmpeg_extract.subprocess.run
        self._orig_which = ffmpeg_extract.shutil.which
        self._orig_path = ffmpeg_extract.config.FFMPEG_PATH
        self._orig_enabled = ffmpeg_extract.config.REFERENCE_VIDEO_FFMPEG_EXTRACT

        ffmpeg_extract.config.FFMPEG_PATH = "ffmpeg"
        ffmpeg_extract.config.REFERENCE_VIDEO_FFMPEG_EXTRACT = True
        ffmpeg_extract.shutil.which = lambda _exe: "/usr/bin/ffmpeg"

    def tearDown(self):
        ffmpeg_extract.subprocess.run = self._orig_run
        ffmpeg_extract.shutil.which = self._orig_which
        ffmpeg_extract.config.FFMPEG_PATH = self._orig_path
        ffmpeg_extract.config.REFERENCE_VIDEO_FFMPEG_EXTRACT = self._orig_enabled

    def test_extract_audio_success_reads_temp_output(self):
        def _fake_run(cmd, capture_output=True, timeout=0):
            _ = capture_output
            _ = timeout
            output_path = cmd[-1]
            with open(output_path, "wb") as f:
                f.write(b"\x00" * 8192)
            return _ProcResult(returncode=0, stderr=b"")

        ffmpeg_extract.subprocess.run = _fake_run
        out = ffmpeg_extract.extract_audio_mp3_for_whisper(
            b"fake-container-bytes",
            max_seconds=90,
            max_output_bytes=64 * 1024,
        )
        self.assertEqual(len(out), 8192)

    def test_extract_audio_raises_when_output_too_large(self):
        def _fake_run(cmd, capture_output=True, timeout=0):
            _ = capture_output
            _ = timeout
            output_path = cmd[-1]
            with open(output_path, "wb") as f:
                f.write(b"\x01" * (2 * 1024))
            return _ProcResult(returncode=0, stderr=b"")

        ffmpeg_extract.subprocess.run = _fake_run
        with self.assertRaises(ffmpeg_extract.FfmpegAudioTooLargeError):
            ffmpeg_extract.extract_audio_mp3_for_whisper(
                b"fake-container-bytes",
                max_seconds=60,
                max_output_bytes=1024,
            )

    def test_extract_audio_raises_with_ffmpeg_stderr_on_failure(self):
        def _fake_run(_cmd, capture_output=True, timeout=0):
            _ = capture_output
            _ = timeout
            return _ProcResult(returncode=1, stderr=b"decoder init failed")

        ffmpeg_extract.subprocess.run = _fake_run
        with self.assertRaises(ffmpeg_extract.FfmpegAudioExtractError) as ctx:
            ffmpeg_extract.extract_audio_mp3_for_whisper(
                b"fake-container-bytes",
                max_seconds=60,
            )
        self.assertIn("decoder init failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
