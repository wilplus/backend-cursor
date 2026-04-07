#!/usr/bin/env python3
"""
Backfill session_sniper_metrics from existing recordings.

Downloads audio from Supabase storage, decodes webm → PCM via ffmpeg,
computes speech metrics (WPM, pause_ms, dynamic_db, emphasis_per_min,
energy_ratio, pitch_center_st), and upserts into session_sniper_metrics.

Run from project root:
  python scripts/backfill_sniper_metrics.py [--user-id UUID] [--dry-run] [--limit N]

Requires: ffmpeg installed (brew install ffmpeg), numpy, .env configured.
"""
import argparse
import io
import logging
import math
import os
import struct
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

# Resolve project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from services.db import db
from utils.metrics import compute_wpm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Audio analysis constants ──
SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SIZE = int(FRAME_MS * SAMPLE_RATE / 1000)  # 320 samples
HOP = FRAME_SIZE  # no overlap
RMS_FLOOR = 1e-8
SILENCE_DB_THRESHOLD = -45.0
MIN_PAUSE_SEC = 0.2  # 200ms minimum pause event

# Pitch detection via autocorrelation
PITCH_MIN_HZ = 75
PITCH_MAX_HZ = 500
PITCH_CONFIDENCE_THRESHOLD = 0.15
PITCH_WINDOW = 2048
PITCH_REF_HZ = 100.0  # semitone reference


def decode_audio_to_pcm(audio_bytes: bytes) -> Optional[np.ndarray]:
    """Decode webm/any audio → 16kHz mono float32 PCM via ffmpeg."""
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-i", "pipe:0",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE), "-ac", "1",
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            logger.warning("ffmpeg failed: %s", proc.stderr[:200])
            return None
        raw = proc.stdout
        if len(raw) < 2:
            return None
        samples = np.frombuffer(raw, dtype=np.int16)
        return samples.astype(np.float32) / 32768.0
    except FileNotFoundError:
        logger.error("ffmpeg not found — install with: brew install ffmpeg")
        sys.exit(1)
    except Exception as e:
        logger.warning("decode_audio_to_pcm error: %s", e)
        return None


def frame_rms_db(sig: np.ndarray) -> np.ndarray:
    """Compute per-frame RMS in dB."""
    dbs = []
    for i in range(0, len(sig) - FRAME_SIZE + 1, HOP):
        frame = sig[i : i + FRAME_SIZE]
        rms = math.sqrt(float(np.mean(frame * frame)) + RMS_FLOOR)
        dbs.append(20.0 * math.log10(rms + RMS_FLOOR))
    return np.array(dbs, dtype=np.float32)


def compute_pause_ms(dbs: np.ndarray) -> Optional[float]:
    """Average pause duration in ms (pauses >= 200ms)."""
    is_silent = dbs < SILENCE_DB_THRESHOLD
    frame_dur_ms = FRAME_MS
    min_frames = int(MIN_PAUSE_SEC * 1000 / frame_dur_ms)

    pause_durations = []
    run_len = 0
    for s in is_silent:
        if s:
            run_len += 1
        else:
            if run_len >= min_frames:
                pause_durations.append(run_len * frame_dur_ms)
            run_len = 0
    if run_len >= min_frames:
        pause_durations.append(run_len * frame_dur_ms)

    if not pause_durations:
        return None
    return round(float(np.mean(pause_durations)), 1)


def compute_dynamic_db(dbs: np.ndarray) -> Optional[float]:
    """Dynamic range: difference between 95th and 5th percentile of voiced frame dBs."""
    voiced_dbs = dbs[dbs >= SILENCE_DB_THRESHOLD]
    if len(voiced_dbs) < 10:
        return None
    p95 = float(np.percentile(voiced_dbs, 95))
    p5 = float(np.percentile(voiced_dbs, 5))
    return round(p95 - p5, 1)


def compute_emphasis_per_min(dbs: np.ndarray, duration_sec: float) -> Optional[float]:
    """Count emphasis events (sudden RMS jumps above local mean) per minute."""
    if duration_sec <= 0 or len(dbs) < 20:
        return None

    voiced_mask = dbs >= SILENCE_DB_THRESHOLD
    voiced_dbs = dbs[voiced_mask]
    if len(voiced_dbs) < 10:
        return None

    mean_db = float(np.mean(voiced_dbs))
    std_db = float(np.std(voiced_dbs))
    if std_db < 0.5:
        return 0.0

    # Emphasis = frame where dB exceeds mean + 1.5*std and previous frame was below
    threshold = mean_db + 1.5 * std_db
    emphasis_count = 0
    prev_above = False
    for i, db_val in enumerate(dbs):
        if not voiced_mask[i]:
            prev_above = False
            continue
        above = db_val >= threshold
        if above and not prev_above:
            emphasis_count += 1
        prev_above = above

    return round(emphasis_count / (duration_sec / 60.0), 1)


def compute_energy_ratio(sig: np.ndarray, dbs: np.ndarray) -> Optional[float]:
    """Ratio of voiced energy to total energy (0-1)."""
    if len(dbs) < 5:
        return None
    voiced_mask = dbs >= SILENCE_DB_THRESHOLD
    n_voiced = int(np.sum(voiced_mask))
    n_total = len(voiced_mask)
    if n_total == 0:
        return None

    # Energy = sum of squared samples in voiced frames vs total
    total_energy = 0.0
    voiced_energy = 0.0
    for i in range(0, len(sig) - FRAME_SIZE + 1, HOP):
        frame = sig[i : i + FRAME_SIZE]
        e = float(np.sum(frame * frame))
        total_energy += e
        frame_idx = i // HOP
        if frame_idx < len(voiced_mask) and voiced_mask[frame_idx]:
            voiced_energy += e

    if total_energy < 1e-12:
        return None
    return round(voiced_energy / total_energy, 3)


def compute_pitch_center_st(sig: np.ndarray) -> Tuple[Optional[float], int]:
    """Compute median pitch in semitones via autocorrelation. Returns (pitch_st, frame_count)."""
    min_lag = int(SAMPLE_RATE / PITCH_MAX_HZ)
    max_lag = int(SAMPLE_RATE / PITCH_MIN_HZ)
    pitch_hz_list = []

    for start in range(0, len(sig) - PITCH_WINDOW + 1, PITCH_WINDOW):
        window = sig[start : start + PITCH_WINDOW]

        # Apply Hamming window
        hamming = np.hamming(PITCH_WINDOW).astype(np.float32)
        windowed = window * hamming

        # Normalized autocorrelation
        norm = float(np.sum(windowed * windowed))
        if norm < 1e-10:
            continue

        autocorr = np.correlate(windowed, windowed, mode="full")
        autocorr = autocorr[PITCH_WINDOW - 1 :]  # keep positive lags
        autocorr = autocorr / (norm + 1e-10)

        # Find peak in valid lag range
        if max_lag >= len(autocorr):
            continue
        search_region = autocorr[min_lag : max_lag + 1]
        if len(search_region) == 0:
            continue

        peak_idx = int(np.argmax(search_region))
        confidence = float(search_region[peak_idx])

        if confidence >= PITCH_CONFIDENCE_THRESHOLD:
            lag = min_lag + peak_idx
            if lag > 0:
                hz = SAMPLE_RATE / lag
                pitch_hz_list.append(hz)

    if not pitch_hz_list:
        return None, 0

    median_hz = float(np.median(pitch_hz_list))
    semitones = 12.0 * math.log2(median_hz / PITCH_REF_HZ)
    return round(semitones, 1), len(pitch_hz_list)


def analyze_audio(sig: np.ndarray, transcript: str, duration_sec: float) -> Dict:
    """Compute all 6 metrics from PCM signal + transcript."""
    dbs = frame_rms_db(sig)
    duration = len(sig) / float(SAMPLE_RATE)
    if duration_sec <= 0:
        duration_sec = duration

    wpm = compute_wpm(transcript, duration_sec) if transcript else None
    pause_ms = compute_pause_ms(dbs)
    dynamic_db = compute_dynamic_db(dbs)
    emphasis = compute_emphasis_per_min(dbs, duration_sec)
    energy = compute_energy_ratio(sig, dbs)
    pitch_st, pitch_frames = compute_pitch_center_st(sig)

    # voiced_duration_sec: total voiced time
    voiced_mask = dbs >= SILENCE_DB_THRESHOLD
    voiced_dur = float(np.sum(voiced_mask)) * (FRAME_MS / 1000.0)

    return {
        "wpm": wpm,
        "pause_ms": pause_ms,
        "dynamic_db": dynamic_db,
        "emphasis_per_min": emphasis,
        "energy_ratio": energy,
        "pitch_center_st": pitch_st,
        "pitch_frame_count": pitch_frames,
        "voiced_duration_sec": round(voiced_dur, 1),
    }


def get_sessions_needing_backfill(user_id: Optional[str], limit: int) -> List[dict]:
    """Get sessions that have recordings but no session_sniper_metrics."""
    query = (
        db.client.table("v2_sessions")
        .select("id, user_id, recording_1_id, completed_at, status")
        .eq("status", "completed")
        .order("completed_at", desc=True)
        .limit(limit)
    )
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.execute()
    sessions = result.data or []

    if not sessions:
        return []

    # Filter out sessions that already have sniper metrics
    session_ids = [s["id"] for s in sessions]
    existing = set()
    # Query in batches of 50 (Supabase in_ limit)
    for i in range(0, len(session_ids), 50):
        batch = session_ids[i : i + 50]
        sm = (
            db.client.table("session_sniper_metrics")
            .select("session_id")
            .in_("session_id", batch)
            .execute()
        )
        for row in sm.data or []:
            existing.add(row["session_id"])

    return [s for s in sessions if s["id"] not in existing and s.get("recording_1_id")]


def get_recording_info(recording_id: str) -> Optional[dict]:
    """Get recording storage_path, transcript, duration."""
    result = (
        db.client.table("recordings")
        .select("id, storage_path, transcription_text, duration, words_per_minute")
        .eq("id", recording_id)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


def backfill_session(session: dict, dry_run: bool) -> bool:
    """Backfill one session. Returns True on success."""
    session_id = session["id"]
    user_id = session["user_id"]
    recording_id = session.get("recording_1_id")

    if not recording_id:
        logger.info("  skip %s — no recording", session_id[:8])
        return False

    rec = get_recording_info(recording_id)
    if not rec:
        logger.info("  skip %s — recording row not found", session_id[:8])
        return False

    storage_path = (rec.get("storage_path") or "").strip()
    if not storage_path:
        logger.info("  skip %s — no storage_path", session_id[:8])
        return False

    transcript = (rec.get("transcription_text") or "").strip()
    duration_raw = rec.get("duration") or 0
    duration_sec = float(duration_raw) if duration_raw else 0.0
    # If duration looks like milliseconds (>10000), convert
    if duration_sec > 10000:
        duration_sec = duration_sec / 1000.0

    # Download audio
    try:
        audio_bytes = db.download_audio(Config.AUDIO_BUCKET_NAME, storage_path)
        if not audio_bytes or len(audio_bytes) < 100:
            logger.info("  skip %s — empty audio (%d bytes)", session_id[:8], len(audio_bytes or b""))
            return False
    except Exception as e:
        logger.warning("  skip %s — download failed: %s", session_id[:8], e)
        return False

    # Decode
    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None or len(sig) < SAMPLE_RATE:
        logger.info("  skip %s — could not decode audio or too short", session_id[:8])
        return False

    # If we don't have duration from DB, compute from audio
    if duration_sec <= 0:
        duration_sec = len(sig) / float(SAMPLE_RATE)

    # Analyze
    metrics = analyze_audio(sig, transcript, duration_sec)

    # Fallback WPM from recording row
    if metrics["wpm"] is None and rec.get("words_per_minute"):
        metrics["wpm"] = round(float(rec["words_per_minute"]), 1)

    logger.info(
        "  %s — wpm=%.0f pause=%s dyn=%.1f emph=%.1f energy=%.3f pitch=%.1f (%d frames) voiced=%.1fs",
        session_id[:8],
        metrics["wpm"] or 0,
        metrics["pause_ms"],
        metrics["dynamic_db"] or 0,
        metrics["emphasis_per_min"] or 0,
        metrics["energy_ratio"] or 0,
        metrics["pitch_center_st"] or 0,
        metrics["pitch_frame_count"] or 0,
        metrics["voiced_duration_sec"] or 0,
    )

    if dry_run:
        logger.info("  [DRY RUN] would upsert session_sniper_metrics for %s", session_id[:8])
        return True

    # Upsert
    try:
        db.save_session_sniper_metrics(
            session_id=session_id,
            user_id=user_id,
            wpm=metrics["wpm"],
            pause_ms=metrics["pause_ms"],
            dynamic_db=metrics["dynamic_db"],
            emphasis_per_min=metrics["emphasis_per_min"],
            energy_ratio=metrics["energy_ratio"],
            voiced_duration_sec=metrics["voiced_duration_sec"],
            recording_id=recording_id,
            duration_seconds=duration_sec,
            pitch_center_st=metrics["pitch_center_st"],
            pitch_frame_count=metrics["pitch_frame_count"],
        )
        return True
    except Exception as e:
        logger.error("  %s — upsert failed: %s", session_id[:8], e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Backfill session_sniper_metrics from recordings")
    parser.add_argument("--user-id", help="Only backfill sessions for this user UUID")
    parser.add_argument("--dry-run", action="store_true", help="Compute metrics but don't write to DB")
    parser.add_argument("--limit", type=int, default=200, help="Max sessions to process (default 200)")
    args = parser.parse_args()

    logger.info("Starting backfill (user=%s, limit=%d, dry_run=%s)", args.user_id or "ALL", args.limit, args.dry_run)

    sessions = get_sessions_needing_backfill(args.user_id, args.limit)
    logger.info("Found %d sessions needing backfill", len(sessions))

    success = 0
    failed = 0
    for i, session in enumerate(sessions, 1):
        logger.info("[%d/%d] session %s (user %s)", i, len(sessions), session["id"][:8], session["user_id"][:8])
        try:
            if backfill_session(session, args.dry_run):
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error("  unexpected error: %s", e)
            failed += 1
        # Small delay to be gentle on Supabase storage
        time.sleep(0.5)

    logger.info("Done: %d succeeded, %d failed/skipped out of %d total", success, failed, len(sessions))


if __name__ == "__main__":
    main()
