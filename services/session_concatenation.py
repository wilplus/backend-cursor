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

from services.db import db
from services.ffmpeg_audio_extract import resolve_ffmpeg_executable
from services.snippet_tables import SNIPPETS_TABLE


logger = logging.getLogger(__name__)


class ConcatError(RuntimeError):
    """Raised when concatenation cannot produce a session recording."""


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def concatenate_session_audio(
    session_id: str,
    *,
    storage_prefix: str = "session_recordings",
    http_timeout_sec: float = 30.0,
    ffmpeg_timeout_sec: float = 300.0,
) -> dict[str, Any]:
    """Glue every interview-turn audio for ``session_id`` into one file.

    See module docstring for the broader migration context. This is the
    pure-function step — no DB writes, only a storage write.

    Args:
        session_id: ``v2_sessions.id`` whose per-turn audio to concatenate.
        storage_prefix: Path prefix inside the audio bucket; the final
            key is ``{storage_prefix}/{session_id}/full.webm``. The
            bucket itself isn't a parameter because
            services.audio_storage owns that decision now — every audio
            write goes to the same bucket.
        http_timeout_sec: Per-file download timeout when fetching the
            per-turn ``audio_segment_path`` URLs (R2 public URLs in prod).
        ffmpeg_timeout_sec: Hard timeout on each ffmpeg invocation.

    Returns:
        Metadata dict described in the module docstring.

    Raises:
        ConcatError: when no turn rows are found, every download fails,
            ffmpeg fails on both paths, or the storage upload fails.
    """

    # 1) Resolve ffmpeg up front so we fail fast instead of after a download.
    ffmpeg_exe = resolve_ffmpeg_executable()
    if not ffmpeg_exe:
        raise ConcatError("ffmpeg binary not found on host")

    # 2) Load interview-turn snippet rows for this session.
    #    We deliberately don't filter on `turn_number IS NOT NULL` here
    #    even though Path A always sets turn_number — the older filter
    #    is source_type IS NULL, which historically distinguishes
    #    Paths A/B from the Path C ML-generator rows. Order by
    #    created_at so the concat'd timeline matches turn chronology.
    try:
        result = (
            db.client.table(SNIPPETS_TABLE)
            .select(
                "id, turn_number, source_type, audio_segment_path, "
                "duration_ms, start_offset_ms, created_at"
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

    raw_rows = result.data or []
    # Diagnostic: surface EXACTLY which rows the SELECT returned and
    # which we kept after the audio_segment_path filter. When the user-
    # visible "concat only has turn 1" symptom shows up, this log line
    # tells us whether the row was missing from the SELECT (visibility
    # / source_type drift), present-but-empty-path (write race),
    # or present-and-downloadable but the HTTP fetch is the culprit.
    raw_summary = [
        (r.get("turn_number"), bool((r.get("audio_segment_path") or "").strip()))
        for r in raw_rows
    ]
    logger.warning(
        "concat:select sid=%s raw_count=%d raw_turns=%s",
        session_id, len(raw_rows), raw_summary,
    )

    rows = [
        r for r in raw_rows
        if (r.get("audio_segment_path") or "").strip()
    ]
    if len(rows) != len(raw_rows):
        dropped = [
            r.get("turn_number") for r in raw_rows
            if not (r.get("audio_segment_path") or "").strip()
        ]
        logger.warning(
            "concat:dropped-empty-path sid=%s dropped_turns=%s",
            session_id, dropped,
        )

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
                turn_num = row.get("turn_number")
                local_path = os.path.join(tmpdir, f"turn_{idx:04d}.webm")
                try:
                    resp = http.get(url)
                    resp.raise_for_status()
                    content = resp.content or b""
                    if not content:
                        logger.warning(
                            "concat:empty sid=%s turn=%s idx=%d url=%s",
                            session_id, turn_num, idx, url,
                        )
                        continue
                    with open(local_path, "wb") as f:
                        f.write(content)
                    local_paths.append(local_path)
                    kept_rows.append(row)
                    logger.warning(
        "concat:fetched sid=%s turn=%s idx=%d bytes=%d",
                        session_id, turn_num, idx, len(content),
                    )
                except Exception as e:
                    # One bad turn shouldn't fail the whole session; we
                    # log and skip it. The returned metadata reflects
                    # only the turns that actually made it into the
                    # concat'd file.
                    logger.warning(
                        "concat:fetch-fail sid=%s turn=%s idx=%d url=%s err=%s",
                        session_id, turn_num, idx, url, e,
                    )

        logger.warning(
        "concat:downloads-complete sid=%s kept=%d expected=%d",
            session_id, len(local_paths), len(rows),
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
            logger.warning(
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

        # 7) Upload the concat'd file to the audio bucket via the
        #    dedicated audio storage helper. Same bucket as the per-turn
        #    inputs (so canonical and source bytes live together) and
        #    same helper as every other interview-audio write — no
        #    chance of read/write bucket drift.
        storage_path = f"{storage_prefix.rstrip('/')}/{session_id}/full.webm"
        with open(out_path, "rb") as f:
            blob = f.read()
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(storage_path, blob, "audio/webm")
        except Exception as e:
            raise ConcatError(
                f"session {session_id}: storage upload failed for "
                f"{storage_path}: {e}"
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

    # Surface the resolved audio bucket name so callers + telemetry can
    # see where the file landed (R2 in production, Supabase fallback in
    # dev). audio_bucket_name() returns "" when R2 isn't configured;
    # callers should treat that as "Supabase Storage at AUDIO_BUCKET_NAME".
    from services.audio_storage import audio_bucket_name as _audio_bucket
    return {
        "session_id": session_id,
        "bucket": _audio_bucket() or "audio_recordings",
        "storage_path": storage_path,
        "duration_ms": probed_duration_ms or sum_durations_ms,
        "turn_snippet_ids": turn_snippet_ids,
        "turn_offsets_ms": turn_offsets_ms,
        "turn_durations_ms": turn_durations_ms,
    }


def finalize_session_recording(session_id: str) -> dict[str, Any]:
    """Concatenate per-turn audio AND rewrite snippet anchors transactionally.

    This is the second step in the migration toward one canonical session
    recording. It calls ``concatenate_session_audio`` (which uploads the
    glued ``.webm`` to storage) and then rewrites each interview-turn
    snippet row so it points into that single file with the right
    cumulative offset:

        storage_path        ← <bucket-relative key of full.webm>
        audio_segment_path  ← NULL   (deprecated for v2 sessions)
        start_offset_ms     ← cumulative offset within concat'd timeline
        duration_ms         ← unchanged

    After this call, every interview-turn snippet plays as a slice of one
    canonical audio: SnippetPreviewPlayer's ``seekTo`` / ``clipEnd`` clamps
    handle the per-snippet trim, and the ±2s buttons only need to mutate
    ``start_offset_ms`` / ``duration_ms`` — no audio re-export.

    Idempotent: re-running on an already-finalized session re-uploads the
    same key (Supabase Storage overwrite-on-upsert) and rewrites the same
    offsets, so it's safe to call from triggers that may fire more than
    once. Rows where the rewrite fails are reported in the return value
    but do not abort the others — the operation is best-effort per row.

    Args:
        session_id: ``v2_sessions.id`` to finalize.

    Returns:
        {
            **concatenate_session_audio return value,
            "n_turns_rewritten": int,
            "n_turns_failed":    int,
            "failed_snippet_ids": [str, ...],
        }

    Raises:
        ConcatError: when the underlying concatenation step fails (no
            turns found, ffmpeg failure, upload failure). DB-write
            failures on individual rows are reported in the return
            value, not raised — one bad row should not block the rest.
    """
    meta = concatenate_session_audio(session_id)

    storage_path = meta["storage_path"]
    turn_ids: list[str] = meta["turn_snippet_ids"]
    offsets_ms: list[int] = meta["turn_offsets_ms"]
    durations_ms: list[int] = meta["turn_durations_ms"]

    n_rewritten = 0
    failed_ids: list[str] = []

    for sid, offset, duration in zip(turn_ids, offsets_ms, durations_ms):
        # We DO NOT null out audio_segment_path here. Two reasons:
        #   1. concatenate_session_audio's SELECT filters by
        #      ``audio_segment_path IS NOT NULL`` to find turn rows;
        #      nulling it would make subsequent finalize calls miss
        #      every row that's already been processed and break
        #      idempotency. (Critical for the auto-trigger that runs
        #      after every turn upload — each call re-finds all turns.)
        #   2. _resolve_snippet_audio_url now prefers storage_path over
        #      audio_segment_path, so once storage_path is populated the
        #      player switches to the concat'd-slice URL automatically.
        #      audio_segment_path is preserved as a historical record /
        #      fallback if signed-URL generation ever fails.
        # duration_ms is echoed back so (start_offset_ms, duration_ms)
        # stays internally consistent even if a stale prior value drifted.
        patch = {
            "storage_path": storage_path,
            "start_offset_ms": int(offset),
            "duration_ms": int(duration),
        }
        try:
            result = (
                db.client.table(SNIPPETS_TABLE)
                .update(patch)
                .eq("id", sid)
                .execute()
            )
            if getattr(result, "data", None):
                n_rewritten += 1
            else:
                # PostgREST returns empty data when no row matched the
                # filter — treat that as a soft failure. The id either
                # got deleted between the concat step and now, or RLS
                # is blocking the write (should never happen with the
                # service-role client, but worth flagging).
                logger.warning(
                    "finalize: empty update result for snippet=%s session=%s",
                    sid, session_id,
                )
                failed_ids.append(sid)
        except Exception as e:
            logger.warning(
                "finalize: rewrite failed snippet=%s session=%s err=%s",
                sid, session_id, e,
            )
            failed_ids.append(sid)

    # Also rewrite recordings.storage_path so the admin's "Full Recording"
    # player — which fetches /v2/admin/recordings/<id>/playback-url and
    # uses recordings.storage_path verbatim — points at the concat'd
    # full.webm instead of the turn-1-only file written at first upload.
    # Without this, Full Recording always shows the duration of turn 1
    # (3 s, in the user's example) instead of the full session (48 s).
    rewritten_recordings = 0
    if turn_ids:
        # Every turn row should share one recording_id (set on turn 1
        # upload and reused on subsequent turns). Read it back from the
        # first turn row.
        try:
            anchor = (
                db.client.table(SNIPPETS_TABLE)
                .select("recording_id")
                .eq("id", turn_ids[0])
                .limit(1)
                .execute()
            )
            recording_id = (
                (anchor.data or [{}])[0].get("recording_id")
                if anchor.data else None
            )
        except Exception as e:
            logger.warning(
                "finalize: failed to read recording_id for session=%s: %s",
                session_id, e,
            )
            recording_id = None

        if recording_id:
            try:
                upd = (
                    db.client.table("recordings")
                    .update({"storage_path": storage_path})
                    .eq("id", recording_id)
                    .execute()
                )
                rewritten_recordings = len(upd.data or [])
                logger.warning(
        "finalize:recording-rewrite sid=%s rid=%s storage=%s "
                    "rows=%d",
                    session_id, recording_id, storage_path,
                    rewritten_recordings,
                )
            except Exception as e:
                logger.warning(
                    "finalize: recording rewrite failed sid=%s rid=%s err=%s",
                    session_id, recording_id, e,
                )

    return {
        **meta,
        "n_turns_rewritten": n_rewritten,
        "n_turns_failed": len(failed_ids),
        "n_recordings_rewritten": rewritten_recordings,
        "failed_snippet_ids": failed_ids,
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
