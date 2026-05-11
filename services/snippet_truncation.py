"""Highlight-snippet extraction from a session's concatenated recording.

Reads the canonical ``session_recordings/<sid>/full.webm`` (produced by
``services.session_concatenation.finalize_session_recording``), splits
it into natural speech units bounded by silence, scores each unit on
five acoustic features, picks the top-N with non-max suppression, and
snaps boundaries to the nearest silence for clean cuts.

This module is the pure-function step: it returns snippet candidates
as plain dicts and writes nothing to the database. The companion
``apply_extracted_snippets`` (in commit 3/5) persists results and
respects manual labels via the freeze-on-label policy.

Algorithm
---------
1. Decode full.webm → 16 kHz mono PCM (re-uses audio_metrics helpers).
2. Frame-level features: RMS dB, pitch (autocorr), voice activity.
3. Find silence runs ≥ MIN_SILENCE_MS; the speech segments between
   them are candidates. Filter by 3 s ≤ duration ≤ 20 s.
4. Score each candidate (composite, 0..1):
     0.35 · energy_peak_z
     0.25 · pitch_variance_z
     0.20 · voiced_ratio
     0.10 · length_sweet_spot (peak at 8 s)
   − 0.10 · filler_density       (when transcript available)
5. NMS: greedy pick by descending score, skip if timeline overlap with
   any already-picked candidate exceeds NMS_OVERLAP_THRESHOLD.
6. Cap at N = min(MAX_SNIPPETS, ceil(total_minutes * SNIPPETS_PER_MIN)).
7. Snap each picked boundary to the nearest silent frame within
   ±BOUNDARY_SNAP_MS, never crossing the candidate's neighbour.

Output shape (per snippet, in concat'd-timeline order):
    {
        "start_offset_ms": int,
        "duration_ms":     int,
        "score":           float,           # 0..1
        "components": {                     # for telemetry / debugging
            "energy_z":      float,
            "pitch_var_z":   float,
            "voiced_ratio":  float,
            "length_fit":    float,
            "filler_density": float,
        },
        "transcript_excerpt": str | None,   # populated by caller using
                                            # session-level transcript +
                                            # the (start, end) offsets
    }

Constants are deliberately exposed at module level so commit 3/5 can
override them in tests / future tuning passes without forking the
algorithm.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from services.audio_metrics import (
    FRAME_MS,
    FRAME_SIZE,
    HOP,
    SAMPLE_RATE,
    SILENCE_DB_THRESHOLD,
    _frame_rms_db,
    _compute_pitch_center_st,
    decode_audio_to_pcm,
)


logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

# Minimum continuous silence that counts as a natural boundary.
MIN_SILENCE_MS: int = 600

# Snippet length filter applied AFTER silence segmentation.
MIN_SNIPPET_MS: int = 3_000
MAX_SNIPPET_MS: int = 20_000

# Sweet-spot for length scoring — tent function peaks at this value.
LENGTH_SWEET_SPOT_MS: int = 8_000

# How much of the recording's mean energy a candidate must exceed to score >0
# on the energy component. (z = (peak_dB − session_mean_dB) / session_std_dB)
ENERGY_Z_NORM: float = 2.0
PITCH_VAR_Z_NORM: float = 2.0

# Composite weights — sum of positive weights = 0.90, filler subtracts up to 0.10.
W_ENERGY = 0.35
W_PITCH_VAR = 0.25
W_VOICED_RATIO = 0.20
W_LENGTH_FIT = 0.10
W_FILLER_PENALTY = 0.10

# Non-max suppression: maximum allowed timeline overlap before we drop the
# lower-scoring candidate. 30 % is a good balance — adjacent moments stay,
# duplicate moments don't.
NMS_OVERLAP_THRESHOLD: float = 0.30

# Cap rule: N = min(MAX_SNIPPETS, ceil(minutes * SNIPPETS_PER_MIN)).
SNIPPETS_PER_MIN: float = 2.0
MAX_SNIPPETS: int = 6

# Boundary snap radius — never cross the candidate's neighbour.
BOUNDARY_SNAP_MS: int = 500

# Filler word list, mirroring services.stress_snippet_service._FILLER_WORDS.
# Kept inline here so the algorithm is self-contained for testing.
_FILLER_WORDS = (
    "um", "uh", "erm", "hmm", "like", "you know", "i mean", "sort of", "kind of",
)


# ── Public API ──────────────────────────────────────────────────────────────


def extract_snippets_from_pcm(
    pcm: np.ndarray,
    *,
    full_transcript: str | None = None,
) -> list[dict[str, Any]]:
    """Pick highlight snippets from a decoded PCM signal.

    Pure function over the signal — no I/O. ``apply_extracted_snippets``
    in commit 3/5 owns the storage download and DB persistence.

    Args:
        pcm: 16 kHz mono PCM as float32 (output of decode_audio_to_pcm).
        full_transcript: Optional whole-session transcript. When present
            we estimate per-window transcript text by proportional time-
            slicing and run a filler-word count for the penalty.

    Returns:
        List of snippet dicts (shape documented in module docstring),
        sorted by ``start_offset_ms`` ascending. May be empty.
    """
    if pcm is None or len(pcm) < SAMPLE_RATE:
        return []

    duration_ms = int(len(pcm) * 1000 / SAMPLE_RATE)
    if duration_ms < MIN_SNIPPET_MS:
        return []

    # 1) Frame-level features
    dbs = _frame_rms_db(pcm)
    voiced_mask = dbs >= SILENCE_DB_THRESHOLD

    # 2) Candidate windows = speech runs between silence runs ≥ MIN_SILENCE_MS
    candidates = _segment_by_silence(voiced_mask, duration_ms)
    candidates = [c for c in candidates
                  if MIN_SNIPPET_MS <= (c[1] - c[0]) <= MAX_SNIPPET_MS]
    if not candidates:
        return []

    # 3) Session-level stats for z-score normalisation
    voiced_dbs = dbs[voiced_mask]
    if len(voiced_dbs) < 10:
        return []
    session_mean_db = float(np.mean(voiced_dbs))
    session_std_db = float(np.std(voiced_dbs)) or 1.0

    # Pitch across the whole signal as a coarse baseline for variance norm.
    # We compute pitch per-candidate too (cheaper than per-frame).
    _, _ = _compute_pitch_center_st(pcm)  # warms caches if any

    # 4) Score candidates
    scored: list[tuple[float, tuple[int, int], dict[str, float], str | None]] = []
    for start_ms, end_ms in candidates:
        score, components, excerpt = _score_candidate(
            pcm=pcm,
            dbs=dbs,
            voiced_mask=voiced_mask,
            start_ms=start_ms,
            end_ms=end_ms,
            session_mean_db=session_mean_db,
            session_std_db=session_std_db,
            total_duration_ms=duration_ms,
            full_transcript=full_transcript,
        )
        if score <= 0:
            continue
        scored.append((score, (start_ms, end_ms), components, excerpt))

    if not scored:
        return []

    # 5) Non-max suppression + 6) cap
    scored.sort(key=lambda x: x[0], reverse=True)
    cap = min(MAX_SNIPPETS, max(1, math.ceil((duration_ms / 60_000.0) * SNIPPETS_PER_MIN)))
    picked: list[tuple[float, tuple[int, int], dict[str, float], str | None]] = []
    for entry in scored:
        if len(picked) >= cap:
            break
        if any(_timeline_overlap(entry[1], p[1]) > NMS_OVERLAP_THRESHOLD for p in picked):
            continue
        picked.append(entry)

    # 7) Snap boundaries to nearest silent frame within ±BOUNDARY_SNAP_MS
    snapped = [
        (score, _snap_boundaries(window, voiced_mask, picked_windows=[p[1] for p in picked]),
         components, excerpt)
        for score, window, components, excerpt in picked
    ]
    # Re-sort by start time so caller writes them in timeline order
    snapped.sort(key=lambda x: x[1][0])

    return [
        {
            "start_offset_ms": int(window[0]),
            "duration_ms": int(window[1] - window[0]),
            "score": round(float(score), 4),
            "components": {k: round(float(v), 4) for k, v in components.items()},
            "transcript_excerpt": excerpt,
        }
        for score, window, components, excerpt in snapped
    ]


def extract_snippets_from_bytes(
    audio_bytes: bytes,
    *,
    full_transcript: str | None = None,
) -> list[dict[str, Any]]:
    """Convenience wrapper: decode ``.webm`` bytes then run extraction.

    Returns ``[]`` when decode fails (ffmpeg missing, corrupt input, etc.)
    so callers don't need separate try/except.
    """
    pcm = decode_audio_to_pcm(audio_bytes)
    if pcm is None:
        logger.warning("snippet_truncation: decode failed — no PCM signal")
        return []
    return extract_snippets_from_pcm(pcm, full_transcript=full_transcript)


def apply_extracted_snippets(session_id: str) -> dict[str, Any]:
    """Run extraction for a session and persist the results to the DB.

    End-to-end pipeline:
      1. Look up the session's concat'd recording (storage_path under
         ``session_recordings/``) and parent recording_id by inspecting
         any turn row.
      2. Pull existing extracted snippets for the session and freeze the
         ones an admin has labeled (coach_label, admin_comment, or a
         non-"unlabeled" snippet_type). Frozen rows are never deleted
         and their timeline windows mask out overlapping candidates.
      3. Build the session-wide transcript from turn rows (in
         turn_number order) for the filler-density penalty.
      4. Download full.webm via services.audio_storage and call
         ``extract_snippets_from_bytes`` to propose candidate windows.
      5. Drop candidates that overlap any frozen window.
      6. Delete prior un-frozen ``source_type='auto_extracted'`` rows in
         one shot.
      7. Insert the surviving candidates as new rows.

    Idempotent: re-running on a session re-runs extraction but preserves
    every labeled snippet exactly. The auto-extracted set converges to
    whatever the algorithm currently outputs minus the frozen mask.

    Returns a summary dict the caller can log; never raises on bad
    session_id / missing recording — those are reported via the dict
    (no-op return). Storage / DB errors propagate.
    """
    from services.audio_storage import get_audio_bytes
    from services.db import db

    # 1) Find the canonical recording for this session by inspecting any
    #    turn row. After finalize_session_recording, every turn row's
    #    storage_path points at session_recordings/<sid>/full.webm.
    turn_anchor = (
        db.client.table("charisma_snippets")
        .select("storage_path, recording_id")
        .eq("session_id", session_id)
        .not_.is_("turn_number", "null")
        .not_.is_("storage_path", "null")
        .limit(1)
        .execute()
    )
    rows = turn_anchor.data or []
    if not rows:
        return {
            "session_id": session_id,
            "skipped": "no_canonical_recording",
            "candidates_proposed": 0,
            "frozen_preserved": 0,
            "new_inserted": 0,
            "deleted": 0,
        }
    concat_storage_path = (rows[0].get("storage_path") or "").strip()
    recording_id = rows[0].get("recording_id")
    if not concat_storage_path.startswith("session_recordings/"):
        # Turn rows still point at per-turn files — concat hasn't run yet
        # (or has been undone). Caller should retry after finalize.
        return {
            "session_id": session_id,
            "skipped": "canonical_not_finalized",
            "candidates_proposed": 0,
            "frozen_preserved": 0,
            "new_inserted": 0,
            "deleted": 0,
        }

    # 2) Pull existing extracted rows for the session and split them
    #    into frozen (labeled) vs unfrozen (eligible for replacement).
    existing = (
        db.client.table("charisma_snippets")
        .select("id, start_offset_ms, duration_ms, source_type, "
                "coach_label, admin_comment, snippet_type")
        .eq("session_id", session_id)
        .is_("turn_number", "null")
        .execute()
    )
    existing_rows = existing.data or []
    frozen: list[dict[str, Any]] = []
    unfrozen_auto_ids: list[str] = []
    for s in existing_rows:
        if _is_frozen(s):
            frozen.append(s)
        elif (s.get("source_type") or "") == "auto_extracted":
            sid = s.get("id")
            if sid:
                unfrozen_auto_ids.append(str(sid))
        # Note: rows with source_type other than auto_extracted and not
        # frozen (e.g. a stale state) are left alone. We don't own them.

    # 3) Build a session-wide transcript from turn rows for the
    #    filler-density penalty. Order by turn_number so the
    #    proportional time-slicing inside extract_snippets_from_pcm
    #    roughly aligns with the recording's timeline.
    turn_rows = (
        db.client.table("charisma_snippets")
        .select("transcript, turn_number")
        .eq("session_id", session_id)
        .not_.is_("turn_number", "null")
        .order("turn_number", desc=False)
        .execute()
    )
    parts = [
        (t.get("transcript") or "").strip()
        for t in (turn_rows.data or [])
        if (t.get("transcript") or "").strip()
    ]
    full_transcript = " ".join(parts).strip() or None

    # 4) Download audio + run the algorithm
    try:
        audio_bytes = get_audio_bytes(concat_storage_path)
    except Exception as e:
        logger.warning(
            "apply_extracted_snippets: download failed session=%s path=%s err=%s",
            session_id, concat_storage_path, e,
        )
        return {
            "session_id": session_id,
            "skipped": "download_failed",
            "candidates_proposed": 0,
            "frozen_preserved": len(frozen),
            "new_inserted": 0,
            "deleted": 0,
        }
    candidates = extract_snippets_from_bytes(
        audio_bytes, full_transcript=full_transcript
    )

    # 5) Drop candidates that overlap any frozen window (timeline IoU > 0)
    def _overlaps_any_frozen(cand: dict[str, Any]) -> bool:
        c_start = int(cand["start_offset_ms"])
        c_end = c_start + int(cand["duration_ms"])
        for f in frozen:
            f_start = int(f.get("start_offset_ms") or 0)
            f_end = f_start + int(f.get("duration_ms") or 0)
            if max(0, min(c_end, f_end) - max(c_start, f_start)) > 0:
                return True
        return False

    new_candidates = [c for c in candidates if not _overlaps_any_frozen(c)]

    # 6) Delete prior un-frozen auto_extracted rows in one shot
    deleted_count = 0
    if unfrozen_auto_ids:
        try:
            del_res = (
                db.client.table("charisma_snippets")
                .delete()
                .in_("id", unfrozen_auto_ids)
                .execute()
            )
            deleted_count = len(del_res.data or unfrozen_auto_ids)
        except Exception as e:
            logger.warning(
                "apply_extracted_snippets: delete failed session=%s err=%s",
                session_id, e,
            )

    # 7) Insert surviving candidates as new auto_extracted rows
    inserted_count = 0
    if new_candidates:
        payload = [
            {
                "session_id": session_id,
                "recording_id": recording_id,
                "storage_path": concat_storage_path,
                "start_offset_ms": int(c["start_offset_ms"]),
                "duration_ms": int(c["duration_ms"]),
                # turn_number stays NULL — this is what distinguishes an
                # extracted snippet from a turn row in /admin/sessions/<id>.
                "source_type": "auto_extracted",
                "transcript": c.get("transcript_excerpt"),
                "snippet_type": "unlabeled",
                # Light-weight metadata for telemetry; the heavy
                # per-snippet metric re-compute is deferred to either
                # the boundary-adjust endpoint or a follow-up commit.
                "metrics": {"extractor_score": c.get("score"),
                            "extractor_components": c.get("components")},
            }
            for c in new_candidates
        ]
        try:
            inserted = db.v2_insert_charisma_snippets(payload)
            inserted_count = len(inserted or [])
        except Exception as e:
            logger.warning(
                "apply_extracted_snippets: insert failed session=%s err=%s",
                session_id, e,
            )

    return {
        "session_id": session_id,
        "storage_path": concat_storage_path,
        "candidates_proposed": len(candidates),
        "frozen_preserved": len(frozen),
        "new_inserted": inserted_count,
        "deleted": deleted_count,
    }


def _is_frozen(snippet: dict[str, Any]) -> bool:
    """An auto-extracted row is frozen once an admin has labeled it.

    Three frozen signals (any one is sufficient):
      - coach_label set (binary classifier label, "charisma" / "stress")
      - admin_comment populated (coach has written feedback)
      - snippet_type set AND not the default "unlabeled"

    Frozen rows are never deleted, and their timeline windows mask out
    overlapping candidates in subsequent extractions.
    """
    if (snippet.get("coach_label") or "").strip():
        return True
    if (snippet.get("admin_comment") or "").strip():
        return True
    snippet_type = (snippet.get("snippet_type") or "").strip().lower()
    if snippet_type and snippet_type != "unlabeled":
        return True
    return False


# ── Internals ───────────────────────────────────────────────────────────────


def _segment_by_silence(voiced_mask: np.ndarray, total_duration_ms: int) -> list[tuple[int, int]]:
    """Return (start_ms, end_ms) runs of speech bounded by silence ≥ MIN_SILENCE_MS.

    Walks the voiced/silent boolean array, accumulating silent runs.
    Whenever a silent run reaches the minimum length, the prior speech
    run becomes a candidate. Final speech run (no trailing silence)
    is also emitted.
    """
    min_silent_frames = max(1, int(MIN_SILENCE_MS / FRAME_MS))
    segments: list[tuple[int, int]] = []

    in_speech = False
    speech_start_frame = 0
    silent_run = 0

    for i, voiced in enumerate(voiced_mask):
        if voiced:
            if not in_speech:
                in_speech = True
                speech_start_frame = i
            silent_run = 0
        else:
            silent_run += 1
            if in_speech and silent_run >= min_silent_frames:
                # The last `silent_run` frames closed the prior speech run.
                speech_end_frame = i - silent_run + 1
                segments.append((
                    speech_start_frame * FRAME_MS,
                    speech_end_frame * FRAME_MS,
                ))
                in_speech = False

    if in_speech:
        segments.append((
            speech_start_frame * FRAME_MS,
            min(total_duration_ms, len(voiced_mask) * FRAME_MS),
        ))

    return segments


def _score_candidate(
    *,
    pcm: np.ndarray,
    dbs: np.ndarray,
    voiced_mask: np.ndarray,
    start_ms: int,
    end_ms: int,
    session_mean_db: float,
    session_std_db: float,
    total_duration_ms: int,
    full_transcript: str | None,
) -> tuple[float, dict[str, float], str | None]:
    """Composite score in [0, 1] for one candidate window.

    Returns (score, components_dict, transcript_excerpt_for_window).
    """
    start_frame = max(0, int(start_ms / FRAME_MS))
    end_frame = min(len(dbs), int(end_ms / FRAME_MS))
    win_dbs = dbs[start_frame:end_frame]
    win_voiced = voiced_mask[start_frame:end_frame]
    if len(win_dbs) < 5 or not bool(win_voiced.any()):
        return 0.0, {}, None

    # Energy component: peak of window relative to session distribution
    voiced_win_dbs = win_dbs[win_voiced]
    if len(voiced_win_dbs) == 0:
        energy_z = 0.0
    else:
        peak_db = float(np.max(voiced_win_dbs))
        energy_z = (peak_db - session_mean_db) / session_std_db
    energy_score = _clamp01(energy_z / ENERGY_Z_NORM)

    # Pitch variance component: how expressive the speaker is in this window
    pitch_var_score = _pitch_variance_score(pcm, start_ms, end_ms)

    # Voiced-ratio component: density of actual speech vs silence within window
    voiced_ratio = float(win_voiced.sum()) / max(1, len(win_voiced))

    # Length-fit component: tent function peaking at LENGTH_SWEET_SPOT_MS
    length_fit = _length_fit_score(end_ms - start_ms)

    # Filler-density penalty: only when transcript present
    excerpt = _slice_transcript_proportional(
        full_transcript, start_ms, end_ms, total_duration_ms
    )
    filler_density = _filler_density(excerpt) if excerpt else 0.0

    composite = (
        W_ENERGY * energy_score
        + W_PITCH_VAR * pitch_var_score
        + W_VOICED_RATIO * voiced_ratio
        + W_LENGTH_FIT * length_fit
        - W_FILLER_PENALTY * filler_density
    )
    composite = _clamp01(composite)

    return composite, {
        "energy_z": energy_score,
        "pitch_var_z": pitch_var_score,
        "voiced_ratio": voiced_ratio,
        "length_fit": length_fit,
        "filler_density": filler_density,
    }, excerpt


def _pitch_variance_score(pcm: np.ndarray, start_ms: int, end_ms: int) -> float:
    """Std of pitch (semitones) within the window, normalised to ~[0,1].

    Reuses ``_compute_pitch_center_st`` on a sub-slice. That helper
    returns the median + confident-frame count; we approximate
    "variance" by re-running it on two halves and taking the absolute
    difference of medians. Cheap; doesn't require touching the
    autocorrelation internals.
    """
    n = max(1, int((end_ms - start_ms) * SAMPLE_RATE / 1000))
    start_sample = max(0, int(start_ms * SAMPLE_RATE / 1000))
    end_sample = min(len(pcm), start_sample + n)
    seg = pcm[start_sample:end_sample]
    if len(seg) < SAMPLE_RATE // 2:
        return 0.0
    half = len(seg) // 2
    pitch_a, _ = _compute_pitch_center_st(seg[:half])
    pitch_b, _ = _compute_pitch_center_st(seg[half:])
    if pitch_a is None or pitch_b is None:
        return 0.0
    spread = abs(float(pitch_a) - float(pitch_b))  # semitones
    # 2 semitones spread between halves → fully expressive (score 1).
    return _clamp01(spread / PITCH_VAR_Z_NORM)


def _length_fit_score(length_ms: int) -> float:
    """Tent function peaking at LENGTH_SWEET_SPOT_MS, 0 at MIN/MAX_SNIPPET_MS."""
    if length_ms < MIN_SNIPPET_MS or length_ms > MAX_SNIPPET_MS:
        return 0.0
    if length_ms <= LENGTH_SWEET_SPOT_MS:
        return (length_ms - MIN_SNIPPET_MS) / max(1, (LENGTH_SWEET_SPOT_MS - MIN_SNIPPET_MS))
    return (MAX_SNIPPET_MS - length_ms) / max(1, (MAX_SNIPPET_MS - LENGTH_SWEET_SPOT_MS))


def _filler_density(text: str) -> float:
    """Filler count per word, clamped to [0, 1]."""
    if not text:
        return 0.0
    low = f" {text.lower()} "
    fillers = 0
    for token in _FILLER_WORDS:
        if " " in token:
            fillers += low.count(f" {token} ")
        else:
            import re as _re
            fillers += len(_re.findall(rf"\b{_re.escape(token)}\b", low))
    word_count = max(1, len(text.split()))
    return _clamp01(fillers / word_count)


def _slice_transcript_proportional(
    full: str | None,
    start_ms: int,
    end_ms: int,
    total_ms: int,
) -> str | None:
    """Best-effort transcript substring for a time window.

    We don't have word-level timestamps from Whisper here (the upload
    endpoint stores just the per-turn transcripts in the snippet rows),
    so we approximate by character-position proportional to the time
    range. Crude but good enough for the filler-density penalty.
    """
    if not full or total_ms <= 0:
        return None
    start_idx = max(0, int(len(full) * (start_ms / total_ms)))
    end_idx = min(len(full), int(len(full) * (end_ms / total_ms)))
    if end_idx <= start_idx:
        return None
    return full[start_idx:end_idx].strip() or None


def _timeline_overlap(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Intersection-over-union of two (start_ms, end_ms) windows."""
    s = max(a[0], b[0])
    e = min(a[1], b[1])
    inter = max(0, e - s)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def _snap_boundaries(
    window: tuple[int, int],
    voiced_mask: np.ndarray,
    picked_windows: list[tuple[int, int]],
) -> tuple[int, int]:
    """Move the window's edges to the nearest silent frame within snap range.

    Won't cross any already-picked window's interior — keeps snippets
    non-overlapping even after the snap. Falls back to the original
    boundary when no silent frame is found in the search radius.
    """
    start_ms, end_ms = window
    snap_radius_frames = max(1, int(BOUNDARY_SNAP_MS / FRAME_MS))

    def _no_cross(candidate_ms: int, *, is_start: bool) -> bool:
        for ws, we in picked_windows:
            if ws == start_ms and we == end_ms:
                continue
            if is_start and ws < candidate_ms < we:
                return False
            if (not is_start) and ws < candidate_ms < we:
                return False
        return True

    start_frame = int(start_ms / FRAME_MS)
    end_frame = int(end_ms / FRAME_MS)

    best_start = start_ms
    for delta in range(snap_radius_frames + 1):
        for sign in (-1, 1):
            f = start_frame + sign * delta
            if 0 <= f < len(voiced_mask) and not voiced_mask[f]:
                cand = f * FRAME_MS
                if _no_cross(cand, is_start=True):
                    best_start = cand
                    break
        else:
            continue
        break

    best_end = end_ms
    for delta in range(snap_radius_frames + 1):
        for sign in (-1, 1):
            f = end_frame + sign * delta
            if 0 <= f < len(voiced_mask) and not voiced_mask[f]:
                cand = f * FRAME_MS
                if _no_cross(cand, is_start=False):
                    best_end = cand
                    break
        else:
            continue
        break

    # Don't let the snap invert the window
    if best_end <= best_start:
        return window
    return (best_start, best_end)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
