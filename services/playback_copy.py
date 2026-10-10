"""A playback copy of every spoken recording, in a format every browser plays
(founder 2026-10-10: "playback on these two doesn't work", on the iPhone and
on Safari on the Mac).

WHY. Every recording is captured as WebM/Opus (useDualCaptureMic asks for
nothing else), and Safari, on the iPhone and on the Mac alike, does not play
those files reliably in an <audio> element: the button turns to Pause and
nothing is heard, worst of all when the player seeks into a Take to play one
slide's window. Chrome plays them; Safari is half of the founder's speakers.

WHAT. Beside each recording ``…/name.webm`` we keep ``…/name.playback.m4a``:
the same audio as AAC in an MP4 with its index at the front (faststart), which
Safari, Chrome and Firefox all play and seek. The original is never touched;
transcription, analysis and the purge inventory keep reading it. Only the
player-facing resolver (services/audio_ref_resolver.resolve_playable_ref)
hands out the copy, and only once it exists.

WHEN IT IS MADE. Right after a recording is stored (put_lab_audio_bytes): a
short practise attempt (under ``INLINE_MAX_BYTES``) during its upload, because
the judgement screen plays it the moment it is saved; a Take in a small
background pool, so its upload never waits on ffmpeg. For recordings stored
before this existed, the first time a player asks for one, in the background
(the resolver serves the original that once and the copy from then on). A page
read never waits on ffmpeg.

DELETION. The copy is the speaker's voice too. Every R2 deletion of a
recording deletes its copy first and fails closed if it cannot
(``delete_playback_copy``), so a purge never leaves the copy behind.

A file with a video stream gets no copy (a video Take keeps its own player),
and anything that fails keeps the original, logged. Switch:
``Config.PLAYBACK_COPY_ENABLED`` (a code constant).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Where spoken recordings live. Decks, coach videos and journal media are
#: never copied.
RECORDING_PREFIXES: tuple[str, ...] = (
    "session_recordings/",
    "guest_funnel/",
    "willab_lab/",
    "snippets/",
    "casual_voice/",
    "mlc3-practice/",
    "confidence-practice/",
)

PLAYBACK_SUFFIX = ".playback.m4a"
PLAYBACK_CONTENT_TYPE = "audio/mp4"

_MISSING_RECHECK_SEC = 30.0
_lock = threading.Lock()
_present: set[tuple[str, str]] = set()
_missing_until: dict[tuple[str, str], float] = {}
_no_copy: set[tuple[str, str]] = set()
_in_flight: set[tuple[str, str]] = set()
_pool: Optional[ThreadPoolExecutor] = None


def _enabled() -> bool:
    try:
        from config import Config

        return bool(getattr(Config, "PLAYBACK_COPY_ENABLED", False))
    except Exception:
        return False


def playback_key(key: Any) -> Optional[str]:
    """The copy's key for a recording key, else None (not a recording)."""
    if not isinstance(key, str):
        return None
    clean = key.strip().lstrip("/")
    if not clean.lower().endswith(".webm"):
        return None
    if not clean.startswith(RECORDING_PREFIXES):
        return None
    return clean[: -len(".webm")] + PLAYBACK_SUFFIX


def _r2_client() -> Any:
    from services.coach_video_storage import _client, coach_videos_use_r2

    if not coach_videos_use_r2():
        return None
    return _client()


def _exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        if code not in ("404", "NoSuchKey", "NotFound"):
            logger.warning("playback copy: head failed %s/%s: %s", bucket, key, e)
        return False


def playable_key(bucket: str, key: str) -> str:
    """The key a player should be handed: the copy when it exists, else the
    original (and the copy is then made in the background). Never raises."""
    try:
        copy = playback_key(key)
        if not copy or not bucket or not _enabled():
            return key
        slot = (bucket, copy)
        with _lock:
            if slot in _present:
                return copy
            if (bucket, key) in _no_copy:
                return key
            recheck = _missing_until.get(slot, 0.0) > time.monotonic()
        if recheck:
            return key
        client = _r2_client()
        if client is None:
            return key
        if _exists(client, bucket, copy):
            with _lock:
                _present.add(slot)
            return copy
        with _lock:
            _missing_until[slot] = time.monotonic() + _MISSING_RECHECK_SEC
        schedule_playback_copy(bucket, key)
        return key
    except Exception as e:
        logger.warning("playback copy: lookup failed %s/%s: %s", bucket, key, e)
        return key


def schedule_playback_copy(bucket: str, key: str) -> None:
    """Make the copy in the background, once per process. Never raises."""
    global _pool
    try:
        if not _enabled() or not playback_key(key) or not bucket:
            return
        slot = (bucket, key)
        with _lock:
            if slot in _in_flight or slot in _no_copy:
                return
            _in_flight.add(slot)
            if _pool is None:
                _pool = ThreadPoolExecutor(max_workers=2,
                                           thread_name_prefix="playback-copy")
            pool = _pool
        pool.submit(_make_guarded, bucket, key)
    except Exception as e:
        logger.warning("playback copy: could not schedule %s/%s: %s",
                       bucket, key, e)


def _make_guarded(bucket: str, key: str) -> None:
    try:
        make_playback_copy(bucket, key)
    except Exception as e:
        logger.warning("playback copy: failed %s/%s: %s", bucket, key, e,
                       exc_info=True)
    finally:
        with _lock:
            _in_flight.discard((bucket, key))


def transcode_to_m4a(data: bytes, *, timeout: float = 120.0) -> Optional[bytes]:
    """AAC-in-MP4 (faststart) bytes for one recording, or None when it has a
    video stream or ffmpeg cannot make it."""
    from services.webm_remux import _ffmpeg

    exe = _ffmpeg()
    if not exe:
        logger.warning("playback copy: no ffmpeg")
        return None
    with tempfile.TemporaryDirectory(prefix="playback-copy-") as tmp:
        src = os.path.join(tmp, "in.webm")
        dst = os.path.join(tmp, "out.m4a")
        with open(src, "wb") as fh:
            fh.write(data)
        proc = subprocess.run(
            [exe, "-nostdin", "-hide_banner", "-y", "-i", src,
             "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "96k",
             "-movflags", "+faststart", "-f", "mp4", dst],
            capture_output=True, timeout=timeout, check=False,
        )
        described = proc.stderr.decode("utf-8", "replace")
        if "Video:" in described:
            return None
        if proc.returncode != 0 or not os.path.isfile(dst):
            logger.warning("playback copy: ffmpeg exit %s", proc.returncode)
            return None
        with open(dst, "rb") as fh:
            out = fh.read()
    return out or None


#: A recording this small (a practise attempt, a few seconds) gets its copy
#: during the upload itself, because it is played the moment it is saved; a
#: Take is long and is copied in the background.
INLINE_MAX_BYTES = 1_500_000


def copy_on_upload(bucket: str, key: str, body: bytes) -> None:
    """After a recording is stored: a short one is copied now, from the bytes
    in hand; a long one in the background. Never raises."""
    try:
        if not _enabled() or not playback_key(key) or not bucket:
            return
        if isinstance(body, (bytes, bytearray)) and len(body) <= INLINE_MAX_BYTES:
            _write_copy(bucket, key, bytes(body))
            return
        schedule_playback_copy(bucket, key)
    except Exception as e:
        logger.warning("playback copy: upload copy failed %s/%s: %s", bucket,
                       key, e, exc_info=True)


def _write_copy(bucket: str, key: str, body: bytes) -> bool:
    copy = playback_key(key)
    client = _r2_client()
    if not copy or client is None:
        return False
    out = transcode_to_m4a(body, timeout=20.0)
    if out is None:
        with _lock:
            _no_copy.add((bucket, key))
        logger.info("playback copy: none for %s/%s (video or unreadable)",
                    bucket, key)
        return False
    client.put_object(Bucket=bucket, Key=copy, Body=out,
                      ContentType=PLAYBACK_CONTENT_TYPE)
    with _lock:
        _present.add((bucket, copy))
        _missing_until.pop((bucket, copy), None)
    logger.info("playback copy: made %s/%s (%d -> %d bytes)", bucket, copy,
                len(body), len(out))
    return True


def make_playback_copy(bucket: str, key: str) -> bool:
    """Read the recording, write its copy. True when the copy now exists."""
    copy = playback_key(key)
    client = _r2_client()
    if not copy or client is None:
        return False
    if _exists(client, bucket, copy):
        with _lock:
            _present.add((bucket, copy))
        return True
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    return _write_copy(bucket, key, body)


def delete_playback_copy(client: Any, bucket: str, key: str) -> None:
    """Delete a recording's copy before the recording itself. Raises on a
    provider error so the caller's deletion fails closed; a copy that was
    never made is not an error (S3 deletes of a missing key succeed)."""
    copy = playback_key(key)
    if not copy or not bucket:
        return
    client.delete_object(Bucket=bucket, Key=copy)
    with _lock:
        _present.discard((bucket, copy))
        _missing_until.pop((bucket, copy), None)


def reset_for_tests() -> None:
    with _lock:
        _present.clear()
        _missing_until.clear()
        _no_copy.clear()
        _in_flight.clear()
