"""
Compute speech metrics from raw audio bytes (webm/any format → PCM via ffmpeg).

Metrics: WPM, pause_ms, dynamic_db, emphasis_per_min, energy_ratio, pitch_center_st.
Used by recording_1_job (automatic) and backfill script.
"""
import logging
import math
import subprocess
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SIZE = int(FRAME_MS * SAMPLE_RATE / 1000)  # 320 samples
HOP = FRAME_SIZE
RMS_FLOOR = 1e-8
SILENCE_DB_THRESHOLD = -45.0
MIN_PAUSE_SEC = 0.2

PITCH_MIN_HZ = 75
PITCH_MAX_HZ = 500
PITCH_CONFIDENCE_THRESHOLD = 0.15
PITCH_WINDOW = 2048
PITCH_REF_HZ = 100.0


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
            logger.warning("ffmpeg decode failed: %s", proc.stderr[:200])
            return None
        raw = proc.stdout
        if len(raw) < 2:
            return None
        samples = np.frombuffer(raw, dtype=np.int16)
        return samples.astype(np.float32) / 32768.0
    except FileNotFoundError:
        logger.warning("ffmpeg not found — audio metrics will be skipped")
        return None
    except Exception as e:
        logger.warning("decode_audio_to_pcm error: %s", e)
        return None


def _frame_rms_db(sig: np.ndarray) -> np.ndarray:
    dbs = []
    for i in range(0, len(sig) - FRAME_SIZE + 1, HOP):
        frame = sig[i : i + FRAME_SIZE]
        rms = math.sqrt(float(np.mean(frame * frame)) + RMS_FLOOR)
        dbs.append(20.0 * math.log10(rms + RMS_FLOOR))
    return np.array(dbs, dtype=np.float32)


def _compute_pause_ms(dbs: np.ndarray) -> Optional[float]:
    is_silent = dbs < SILENCE_DB_THRESHOLD
    min_frames = int(MIN_PAUSE_SEC * 1000 / FRAME_MS)
    pause_durations = []
    run_len = 0
    for s in is_silent:
        if s:
            run_len += 1
        else:
            if run_len >= min_frames:
                pause_durations.append(run_len * FRAME_MS)
            run_len = 0
    if run_len >= min_frames:
        pause_durations.append(run_len * FRAME_MS)
    if not pause_durations:
        return None
    return round(float(np.mean(pause_durations)), 1)


def _compute_dynamic_db(dbs: np.ndarray) -> Optional[float]:
    voiced_dbs = dbs[dbs >= SILENCE_DB_THRESHOLD]
    if len(voiced_dbs) < 10:
        return None
    return round(float(np.percentile(voiced_dbs, 95) - np.percentile(voiced_dbs, 5)), 1)


def _compute_emphasis_per_min(dbs: np.ndarray, duration_sec: float) -> Optional[float]:
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


def _compute_energy_ratio(sig: np.ndarray, dbs: np.ndarray) -> Optional[float]:
    if len(dbs) < 5:
        return None
    voiced_mask = dbs >= SILENCE_DB_THRESHOLD
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


def _compute_pitch_center_st(sig: np.ndarray) -> Tuple[Optional[float], int]:
    min_lag = int(SAMPLE_RATE / PITCH_MAX_HZ)
    max_lag = int(SAMPLE_RATE / PITCH_MIN_HZ)
    pitch_hz_list = []
    for start in range(0, len(sig) - PITCH_WINDOW + 1, PITCH_WINDOW):
        window = sig[start : start + PITCH_WINDOW]
        hamming = np.hamming(PITCH_WINDOW).astype(np.float32)
        windowed = window * hamming
        norm = float(np.sum(windowed * windowed))
        if norm < 1e-10:
            continue
        autocorr = np.correlate(windowed, windowed, mode="full")
        autocorr = autocorr[PITCH_WINDOW - 1 :]
        autocorr = autocorr / (norm + 1e-10)
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
                pitch_hz_list.append(SAMPLE_RATE / lag)
    if not pitch_hz_list:
        return None, 0
    median_hz = float(np.median(pitch_hz_list))
    semitones = 12.0 * math.log2(median_hz / PITCH_REF_HZ)
    return round(semitones, 1), len(pitch_hz_list)


def analyze_audio(audio_bytes: bytes, transcript: str = "", duration_sec: float = 0.0, fallback_wpm: float = None) -> Optional[Dict]:
    """
    Full audio analysis pipeline. Returns dict with all 6 metrics + voiced_duration_sec,
    or None if audio can't be decoded.
    """
    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None or len(sig) < SAMPLE_RATE:
        return None

    if duration_sec <= 0:
        duration_sec = len(sig) / float(SAMPLE_RATE)

    dbs = _frame_rms_db(sig)
    voiced_mask = dbs >= SILENCE_DB_THRESHOLD
    voiced_dur = float(np.sum(voiced_mask)) * (FRAME_MS / 1000.0)

    # WPM from transcript
    wpm = None
    if transcript and duration_sec > 0:
        word_count = len(transcript.split())
        wpm = round(word_count / (duration_sec / 60.0), 1)
    if wpm is None and fallback_wpm is not None:
        wpm = round(float(fallback_wpm), 1)

    pitch_st, pitch_frames = _compute_pitch_center_st(sig)

    return {
        "wpm": wpm,
        "pause_ms": _compute_pause_ms(dbs),
        "dynamic_db": _compute_dynamic_db(dbs),
        "emphasis_per_min": _compute_emphasis_per_min(dbs, duration_sec),
        "energy_ratio": _compute_energy_ratio(sig, dbs),
        "pitch_center_st": pitch_st,
        "pitch_frame_count": pitch_frames,
        "voiced_duration_sec": round(voiced_dur, 1),
    }
