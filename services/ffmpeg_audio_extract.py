"""
Extract a compressed audio track from video bytes for OpenAI Whisper (25MB file limit).
Uses ffmpeg temp input/output files; resolve_ffmpeg_executable() uses system PATH or
imageio-ffmpeg's bundled binary (see requirements.txt) when the host has no system ffmpeg.
"""
from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
import tempfile

from config import Config

config = Config()
logger = logging.getLogger(__name__)

# Whisper accepts mp3; keep bitrate modest to stay under ~25MB for long clips.
_WHISPER_TARGET_AUDIO_ARGS = [
    "-vn",
    "-ac",
    "1",
    "-ar",
    "16000",
    "-acodec",
    "libmp3lame",
    "-b:a",
    "48k",
    "-f",
    "mp3",
]


class FfmpegAudioExtractError(RuntimeError):
    """Raised when ffmpeg extraction cannot produce a valid Whisper input."""


class FfmpegAudioTooLargeError(FfmpegAudioExtractError):
    """Raised when extracted audio still exceeds the Whisper request size limit."""

    def __init__(self, size_bytes: int, max_bytes: int):
        self.size_bytes = int(size_bytes)
        self.max_bytes = int(max_bytes)
        super().__init__(f"Extracted audio is too large ({self.size_bytes} bytes > {self.max_bytes} bytes)")


def _try_executable_path(candidate: str | None) -> str | None:
    if not candidate or not str(candidate).strip():
        return None
    c = str(candidate).strip()
    if os.path.isabs(c) and os.path.isfile(c) and os.access(c, os.X_OK):
        return c
    w = shutil.which(c)
    return w if w and os.path.isfile(w) and os.access(w, os.X_OK) else None


@functools.lru_cache(maxsize=1)
def resolve_ffmpeg_executable() -> str | None:
    """
    System ffmpeg (PATH / FFMPEG_PATH), then common install paths, then imageio-ffmpeg
    (bundled binary from requirements; works when the host has no system ffmpeg e.g. Railway).
    """
    for probe in (config.FFMPEG_PATH, "ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        p = _try_executable_path(probe)
        if p:
            return p
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]

        p = _try_executable_path(imageio_ffmpeg.get_ffmpeg_exe())
        if p:
            logger.info("using imageio-ffmpeg binary at %s", p)
        return p
    except Exception as e:
        logger.debug("imageio-ffmpeg not available: %s", e)
    return None


def ffmpeg_available() -> bool:
    return bool(resolve_ffmpeg_executable())


def extract_audio_mp3_for_whisper(
    video_bytes: bytes,
    *,
    max_seconds: int,
    max_output_bytes: int = 24 * 1024 * 1024,
) -> bytes:
    """
    Decode container bytes and return MP3 bytes suitable for whisper-1.
    Uses temporary files (input + output) and cleans them up automatically.
    Raises FfmpegAudioExtractError / FfmpegAudioTooLargeError on failure.
    """
    if not video_bytes:
        raise FfmpegAudioExtractError("Input file is empty; cannot extract audio.")
    if not config.REFERENCE_VIDEO_FFMPEG_EXTRACT:
        raise FfmpegAudioExtractError(
            "ffmpeg extraction is disabled (REFERENCE_VIDEO_FFMPEG_EXTRACT=false)."
        )
    exe = resolve_ffmpeg_executable()
    if not exe:
        raise FfmpegAudioExtractError(
            f"ffmpeg not found (FFMPEG_PATH={config.FFMPEG_PATH!r}; no imageio-ffmpeg binary)."
        )

    cap = max(30, min(24 * 3600, int(max_seconds)))
    timeout_s = max(120.0, min(3600.0, cap * 0.15 + 60.0))
    try:
        with tempfile.TemporaryDirectory(prefix="whisper-audio-") as tmp_dir:
            input_path = os.path.join(tmp_dir, "input-container.bin")
            output_path = os.path.join(tmp_dir, "output-audio.mp3")
            with open(input_path, "wb") as in_file:
                in_file.write(video_bytes)

            cmd = [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                input_path,
                "-t",
                str(cap),
                *_WHISPER_TARGET_AUDIO_ARGS,
                output_path,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_s,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")[:2000]
                raise FfmpegAudioExtractError(f"ffmpeg exited with code {proc.returncode}: {err}")

            if not os.path.exists(output_path):
                raise FfmpegAudioExtractError("ffmpeg reported success but produced no output file.")
            out_size = os.path.getsize(output_path)
            if out_size < 256:
                raise FfmpegAudioExtractError(
                    f"ffmpeg output is too small ({out_size} bytes); likely no audio track."
                )
            if out_size > int(max_output_bytes):
                raise FfmpegAudioTooLargeError(out_size, int(max_output_bytes))

            with open(output_path, "rb") as out_file:
                return out_file.read()
    except subprocess.TimeoutExpired as timeout_err:
        raise FfmpegAudioExtractError(
            f"ffmpeg audio extraction timed out after {int(timeout_s)}s."
        ) from timeout_err
    except FfmpegAudioExtractError:
        raise
    except Exception as e:
        logger.error("ffmpeg audio extract failed unexpectedly: %s", e, exc_info=True)
        raise FfmpegAudioExtractError(str(e)) from e
