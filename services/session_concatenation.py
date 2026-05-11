"""Concatenate per-turn interview audio into one canonical session recording.

Problem this solves
-------------------
v2 interview sessions today upload one ``.webm`` per turn to public R2
(``guest_funnel/<session-id>/turn_<N>_<hash>.webm``). Each per-turn URL
is persisted on the snippet row in ``charisma_snippets.audio_segment_path``
with ``start_offset_ms = 0`` — i.e. every snippet treats its turn file
as a standalone audio.

That model has two failure modes:
  1. The admin's "±2s" boundary controls have to re-cut a per-snippet
     audio file every time bounds change, instead of being a pure DB
     update.
  2. There is no single canonical recording the admin can scrub through
     to listen end-to-end.

This module is the first commit in the migration toward a single
canonical session recording. It exposes a pure function:

    concatenate_session_audio(session_id) -> dict

which downloads every interview-turn ``.webm`` for the session,
concatenates them with ffmpeg (stream-copy fast path, libopus
re-encode fallback), uploads the result to Supabase Storage at
``session_recordings/<session_id>/full.webm``, and returns the
metadata a follow-up step needs to rewrite snippet anchors:

    {
        "session_id":        str,
        "bucket":            str,         # Supabase Storage bucket
        "storage_path":      str,         # key within bucket
        "duration_ms":       int,         # probed length of concat'd file
        "turn_snippet_ids":  [str, ...],  # in concat order
        "turn_offsets_ms":   [int, ...],  # cumulative start within concat'd timeline
        "turn_durations_ms": [int, ...],  # from charisma_snippets.duration_ms
    }

This commit is intentionally side-effect-free with respect to the DB:
it writes the audio file to storage but does NOT update any rows. The
follow-up commit (``finalize_session_recording``) takes the returned
metadata and rewrites ``charisma_snippets`` anchors transactionally.

Why split it that way: keeping the ffmpeg/upload step idempotent and
DB-write-free makes it safe to run multiple times during development
without polluting snippet rows.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import tempfile
from typing import Any

import httpx

from config import Config
from services.db import db
from services.ffmpeg_audio_extract import resolve_ffmpeg_executable


logger = logging.getLogger(__name__)


class ConcatError(RuntimeError):
    """Raised when concatenation cannot produce a session recording."""


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def concatenate_session_audio(
    session_id: str,
    *,
    bucket: str | None = None,
    storage_prefix: str = "session_recordings",
    http_timeout_sec: float = 30.0,
    ffmpeg_timeout_sec: float = 300.0,
) -> dict[str, Any]:
    """Glue every interview-turn audio for ``session_id`` into one file.

    See module docstring for the broader migration context. This is the
    pure-function step — no DB writes, only a storage write.

    Args:
        session_id: ``v2_sessions.id`` whose per-turn audio to concatenate.
        bucket: Supabase Storage bucket to write into. Defaults to
            ``config.AUDIO_BUCKET_NAME`` so the result lives next to the
            existing ``charisma_snippets`` audio assets and ``_resolve_
            snippet_audio_url`` can sign URLs for it with no new code.
        storage_prefix: Path prefix inside the bucket; the final key is
            ``{storage_prefix}/{session_id}/full.webm``.
        http_timeout_sec: Per-file download timeout when fetching the
            current public-R2 ``audio_segment_path`` URLs.
        ffmpeg_timeout_sec: Hard timeout on each ffmpeg invocation.

    Returns:
        Metadata dict described in the module docstring.

    Raises:
        ConcatError: when no turn rows are found, every download fails,
            ffmpeg fails on both paths, or the storage upload fails.
    """
    cfg = Config()
    target_bucket = bucket or cfg.AUDIO_BUCKET_NAME

    # 1) Resolve ffmpeg up front so we fail fast instead of after a download.
    ffmpeg_exe = resolve_ffmpeg_executable()
    if not ffmpeg_exe:
        raise ConcatError("ffmpeg binary not found on host")

    # 2) Load interview-turn snippet rows for this session.
    #    Filter: source_type IS NULL identifies Path A interview rows
    #    (Path C / student rows have a non-null source_type). Order by
    #    created_at so the concat'd timeline matches turn chronology.
    try:
        result = (
            db.client.table("charisma_snippets")
            .select(
                "id, audio_segment_path, duration_ms, "
                "start_offset_ms, created_at"
            )
            .eq("session_id", session_id)
            .is_("source_type", "null")
            .order("created_at", desc=False)
            .execute()
        )
    except Exception as e:
        raise ConcatError(
            f"session {session_id}: failed to load snippet rows: {e}"
        ) from e

    rows = [
        r for r in (result.data or [])
        if (r.get("audio_segment_path") or "").strip()
    ]
    if not rows:
        raise ConcatError(
            f"session {session_id}: no interview-turn rows with "
            "audio_segment_path to concatenate"
        )

    # 3) Download each turn file to a temp workdir.
    with tempfile.TemporaryDirectory(prefix=f"concat_{session_id}_") as tmpdir:
        local_paths: list[str] = []
        kept_rows: list[dict[str, Any]] = []  # rows whose downloads succeeded

        with httpx.Client(timeout=http_timeout_sec, follow_redirects=True) as http:
            for idx, row in enumerate(rows):
                url = (row.get("audio_segment_path") or "").strip()
                local_path = os.path.join(tmpdir, f"turn_{idx:04d}.webm")
                try:
                    resp = http.get(url)
                    resp.raise_for_status()
                    content = resp.content or b""
                    if not content:
                        logger.warning(
                            "concat: empty body for turn idx=%d url=%s",
                            idx, url,
                        )
                        continue
                    with open(local_path, "wb") as f:
                        f.write(content)
                    local_paths.append(local_path)
                    kept_rows.append(row)
                except Exception as e:
                    # One bad turn shouldn't fail the whole session; we
                    # log and skip it. The returned metadata reflects
                    # only the turns that actually made it into the
                    # concat'd file.
                    logger.warning(
                        "concat: skipping turn idx=%d url=%s err=%s",
                        idx, url, e,
                    )

        if not local_paths:
            raise ConcatError(
                f"session {session_id}: all per-turn downloads failed"
            )

        # 4) Build the ffmpeg concat-demuxer manifest.
        concat_list_path = os.path.join(tmpdir, "concat.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for p in local_paths:
                # The concat demuxer expects: file '<path>'
                # shlex.quote handles spaces / single quotes safely.
                f.write(f"file {shlex.quote(p)}\n")

        out_path = os.path.join(tmpdir, "full.webm")

        # 5) Try the cheap stream-copy first. Falls back to opus re-encode
        #    if inputs differ in sample-rate / channel-count and codec-copy
        #    refuses.
        rc, stderr = _run_ffmpeg(
            [
                ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                out_path,
            ],
            timeout_sec=ffmpeg_timeout_sec,
        )
        if rc != 0 or not (os.path.exists(out_path) and os.path.getsize(out_path) > 0):
            logger.info(
                "concat: stream-copy failed for session=%s rc=%d — "
                "retrying with libopus re-encode. stderr_tail=%s",
                session_id, rc, stderr[-500:],
            )
            rc, stderr = _run_ffmpeg(
                [
                    ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_list_path,
                    "-c:a", "libopus", "-b:a", "64k",
                    out_path,
                ],
                timeout_sec=ffmpeg_timeout_sec,
            )

        if rc != 0 or not (os.path.exists(out_path) and os.path.getsize(out_path) > 0):
            raise ConcatError(
                f"session {session_id}: ffmpeg failed on both stream-copy "
                f"and re-encode (rc={rc}). stderr_tail={stderr[-500:]}"
            )

        # 6) Probe the resulting file's duration for the return value
        #    (sanity check + caller may want it for logging / metrics).
        probed_duration_ms = _probe_duration_ms(out_path, ffmpeg_exe)

        # 7) Upload to Supabase Storage. Reusing db.upload_audio means the
        #    bucket-name validation + content-type normalisation match the
        #    rest of the codebase exactly.
        storage_path = f"{storage_prefix.rstrip('/')}/{session_id}/full.webm"
        with open(out_path, "rb") as f:
            blob = f.read()
        try:
            db.upload_audio(target_bucket, storage_path, blob, "audio/webm")
        except Exception as e:
            raise ConcatError(
                f"session {session_id}: storage upload failed for "
                f"{target_bucket}/{storage_path}: {e}"
            ) from e

    # 8) Build the offsets the follow-up step will write back to snippet rows.
    #    Cumulative duration = start_offset for the next turn. We use the DB
    #    duration_ms as the source of truth (not the probed value) because
    #    callers will write these same numbers back as `start_offset_ms` —
    #    keeping the offsets aligned with what the metrics pipeline already
    #    knows about each turn.
    turn_snippet_ids: list[str] = []
    turn_offsets_ms: list[int] = []
    turn_durations_ms: list[int] = []
    cursor = 0
    for row in kept_rows:
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        dur = int(row.get("duration_ms") or 0)
        turn_snippet_ids.append(sid)
        turn_offsets_ms.append(cursor)
        turn_durations_ms.append(dur)
        cursor += dur

    sum_durations_ms = cursor
    if probed_duration_ms and abs(probed_duration_ms - sum_durations_ms) > 1500:
        # Mild log if the probed file length disagrees with the sum of
        # per-turn durations by more than 1.5s — usually means one turn's
        # metric duration_ms is stale. Non-fatal; offsets still work
        # because they're derived from the same DB values the rest of the
        # system uses.
        logger.warning(
            "concat: session=%s duration mismatch — probed=%dms sum=%dms",
            session_id, probed_duration_ms, sum_durations_ms,
        )

    return {
        "session_id": session_id,
        "bucket": target_bucket,
        "storage_path": storage_path,
        "duration_ms": probed_duration_ms or sum_durations_ms,
        "turn_snippet_ids": turn_snippet_ids,
        "turn_offsets_ms": turn_offsets_ms,
        "turn_durations_ms": turn_durations_ms,
    }


# ----------------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------------


def _run_ffmpeg(cmd: list[str], *, timeout_sec: float) -> tuple[int, str]:
    """Run an ffmpeg invocation; return (returncode, stderr).

    Captures stderr text (ffmpeg sends progress + errors there). On
    TimeoutExpired we synthesise a non-zero rc and a synthetic stderr
    so the caller's fallback / error path stays uniform.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return proc.returncode, (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"ffmpeg timed out after {timeout_sec}s: {e}"
    except FileNotFoundError as e:
        return 127, f"ffmpeg binary not found: {e}"


def _probe_duration_ms(path: str, ffmpeg_path: str) -> int:
    """Return the audio file's duration in ms via ffprobe.

    Falls back to 0 on any failure — the caller has the DB-side
    duration sum to use as a fallback total. Tries ``ffprobe`` next to
    the resolved ffmpeg binary first, then ``ffprobe`` on PATH.
    """
    candidates = []
    ffmpeg_dir = os.path.dirname(ffmpeg_path) if ffmpeg_path else ""
    if ffmpeg_dir:
        candidates.append(os.path.join(ffmpeg_dir, "ffprobe"))
    candidates.append("ffprobe")

    for ffprobe in candidates:
        try:
            proc = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                continue
            sec = float((proc.stdout or "0").strip() or "0")
            return int(round(sec * 1000))
        except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
            continue
        except Exception as e:
            logger.debug("ffprobe attempt failed (%s): %s", ffprobe, e)
            continue
    return 0
