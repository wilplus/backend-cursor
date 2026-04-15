"""
Extract a compressed audio track from video bytes for OpenAI Whisper (25MB file limit).
Uses ffmpeg stdin/stdout; requires ffmpeg installed on the host (see apt.txt for Railway).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

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


def ffmpeg_available() -> bool:
    path = config.FFMPEG_PATH
    return bool(path and shutil.which(path))


def extract_audio_mp3_for_whisper(video_bytes: bytes, *, max_seconds: int) -> Optional[bytes]:
    """
    Decode video from memory and return MP3 bytes suitable for whisper-1.
    Returns None if ffmpeg is missing or fails.
    """
    if not video_bytes:
        return None
    if not config.REFERENCE_VIDEO_FFMPEG_EXTRACT:
        return None
    exe = config.FFMPEG_PATH
    if not shutil.which(exe):
        logger.warning("ffmpeg not found at %s; cannot extract audio for Whisper", exe)
        return None

    cap = max(30, min(24 * 3600, int(max_seconds)))
    cmd = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-t",
        str(cap),
        *_WHISPER_TARGET_AUDIO_ARGS,
        "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=video_bytes,
            capture_output=True,
            timeout=max(120.0, min(3600.0, cap * 0.15 + 60.0)),
        )
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg audio extract timed out (cap_s=%s)", cap)
        return None
    except Exception as e:
        logger.error("ffmpeg audio extract failed: %s", e, exc_info=True)
        return None

    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:2000]
        logger.warning("ffmpeg exited %s: %s", proc.returncode, err)
        return None

    out = proc.stdout or b""
    if len(out) < 256:
        logger.warning("ffmpeg produced very small output (%s bytes); likely no audio", len(out))
        return None
    # OpenAI Whisper limit ~25MB
    if len(out) > 25 * 1024 * 1024:
        logger.warning("extracted audio still exceeds 25MB (%s bytes); increase compression or lower max_seconds", len(out))
        return None
    return out
