"""Lossless WebM remux on upload, so a clip can seek inside its parent Take.

WHY (founder 2026-10-08, "make sure the playbacks work all across the app").
Takes and practise tries arrive as MediaRecorder WebM/Opus: a live-style file
with no Cues (seek index) and no Duration. Every clip the app plays is a
window (start_offset_ms + duration_ms) inside that parent file, and Safari
cannot seek a WebM without Cues, so the window either plays from the start
or never plays.

WHAT. ``ffmpeg -i in.webm -map 0 -c copy -copyts -f webm out.webm`` rewrites
the container only: the Opus packets are copied byte for byte, and the muxer
writes Cues and a Duration. ``-copyts`` is load-bearing. Without it ffmpeg
re-bases the timeline: an Opus WebM whose first packet sits at -7 ms (the
codec delay) comes out starting at 0, every packet shifted by 7 ms, which
would move every stored offset against the audio it indexes. With it the
packet timestamps are kept exactly.

FAIL-SAFE (LIVE LOOP). The remux never blocks a Take:

* any ffmpeg error, a missing binary, or a timeout keeps the original bytes;
* the output must be a non-empty EBML file of comparable size;
* and the output must carry EXACTLY the input's packets: one demux pass over
  each (``-f framecrc``, no decode) lists every packet's stream, dts, pts,
  duration, size and checksum, and any difference keeps the original bytes.

So the bytes that reach storage and analysis are either the original or a
file whose every packet and timestamp is proven identical to it. Turned off
by ``Config.WEBM_REMUX_ON_UPLOAD`` (a code constant).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from typing import Optional

logger = logging.getLogger(__name__)

_EBML_MAGIC = b"\x1a\x45\xdf\xa3"


def _enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "WEBM_REMUX_ON_UPLOAD", False))


def _timeout_sec() -> float:
    from config import Config
    try:
        return max(1.0, float(getattr(Config, "WEBM_REMUX_TIMEOUT_SEC", 8)))
    except (TypeError, ValueError):
        return 8.0


def is_webm(data: bytes) -> bool:
    """An EBML file whose DocType is webm (the header names it early)."""
    return (isinstance(data, (bytes, bytearray)) and data[:4] == _EBML_MAGIC
            and b"webm" in bytes(data[:64]))


def _ffmpeg() -> Optional[str]:
    try:
        from services.ffmpeg_audio_extract import resolve_ffmpeg_executable
        return resolve_ffmpeg_executable()
    except Exception as e:
        logger.warning("webm remux: no ffmpeg: %s", e, exc_info=True)
        return None


def _run(args: list, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=max(0.5, timeout), check=False,
    )


def packet_lines(exe: str, path: str, timeout: float) -> Optional[list]:
    """Every packet of ``path`` as framecrc lines (stream, dts, pts,
    duration, size, checksum), demuxed only — or None on failure."""
    proc = _run([exe, "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-i", path, "-map", "0", "-c", "copy", "-copyts",
                 "-f", "framecrc", "-"], timeout)
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in proc.stdout.decode("utf-8", "replace").splitlines()
             if ln.strip() and not ln.startswith("#")]
    return lines or None


def remux_webm_for_seeking(data: bytes, *, label: str = "upload") -> bytes:
    """The remuxed bytes, or ``data`` unchanged on ANY doubt. Never raises."""
    try:
        if not _enabled() or not is_webm(data):
            return data
        exe = _ffmpeg()
        if not exe:
            logger.warning("webm remux skipped (%s): no ffmpeg", label)
            return data
        out = _remux(exe, bytes(data), label)
        return out if out is not None else data
    except Exception as e:
        logger.warning("webm remux skipped (%s): %s", label, e, exc_info=True)
        return data


def _remux(exe: str, data: bytes, label: str) -> Optional[bytes]:
    budget = _timeout_sec()
    started = time.monotonic()

    def left() -> float:
        return budget - (time.monotonic() - started)

    with tempfile.TemporaryDirectory(prefix="webm-remux-") as tmp:
        src = os.path.join(tmp, "in.webm")
        dst = os.path.join(tmp, "out.webm")
        with open(src, "wb") as fh:
            fh.write(data)
        try:
            proc = _run([exe, "-nostdin", "-hide_banner", "-loglevel", "error",
                         "-y", "-i", src, "-map", "0", "-c", "copy", "-copyts",
                         "-f", "webm", dst], left())
            if proc.returncode != 0 or not os.path.isfile(dst):
                logger.warning("webm remux kept original (%s): ffmpeg exit %s",
                               label, proc.returncode)
                return None
            with open(dst, "rb") as rfh:
                out = rfh.read()
            if (not out or out[:4] != _EBML_MAGIC
                    or len(out) < int(len(data) * 0.9)):
                logger.warning("webm remux kept original (%s): implausible output "
                               "(%d -> %d bytes)", label, len(data), len(out))
                return None
            before = packet_lines(exe, src, left())
            after = packet_lines(exe, dst, left())
        except subprocess.TimeoutExpired:
            logger.warning("webm remux kept original (%s): timeout after %.1fs",
                           label, budget)
            return None
        if before is None or after is None or before != after:
            logger.warning("webm remux kept original (%s): packets differ", label)
            return None
        logger.info("webm remux ok (%s): %d -> %d bytes, %d packets, %.0f ms",
                    label, len(data), len(out), len(after),
                    (time.monotonic() - started) * 1000)
        return out
