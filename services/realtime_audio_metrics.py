"""
Real-time audio metrics for Ambient Glow (stateless).
Input: PCM16 mono, 16 kHz (or other rate via sample_rate).
Output: raw + lightly normalized features for frontend to smooth (EMA + rolling window).
"""
import math
from typing import Optional

import numpy as np

# Human pitch range (Hz) for autocorrelation search
F0_MIN_HZ = 75
F0_MAX_HZ = 400
# Frame size for VAD and F0 (ms)
FRAME_MS = 25
# Overlap hop (ms)
HOP_MS = 10
# RMS floor for dB (avoid -inf)
RMS_FLOOR = 1e-10
# Energy threshold for "voiced" frame (relative to max in chunk)
VOICED_THRESHOLD_RATIO = 0.02


def process_pcm_chunk(
    pcm_bytes: bytes,
    sample_rate: int,
    seq: int = 0,
    t_ms: int = 0,
) -> dict:
    """
    Process one chunk of PCM16 little-endian mono audio.
    Returns raw + lightly normalized features for frontend smoothing.

    Args:
        pcm_bytes: Raw PCM16 LE bytes (2 bytes per sample).
        sample_rate: Sample rate in Hz (expect 16000).
        seq: Chunk sequence number (echoed in response).
        t_ms: Client timestamp or sample offset in ms (echoed in response).

    Returns:
        Dict with: seq, t_ms, rms_db, voiced_ratio, f0_hz_mean, f0_hz_std,
                   intonation_proxy (0-1), pace_proxy (0-1).
    """
    if len(pcm_bytes) < 2:
        return _empty_response(seq, t_ms)

    try:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if samples.size == 0:
            return _empty_response(seq, t_ms)
        # Convert to float in [-1, 1]
        sig = samples.astype(np.float32) / 32768.0

        # RMS and dB
        rms = float(np.sqrt(np.mean(sig * sig)) + RMS_FLOOR)
        rms_db = 20.0 * math.log10(rms) if rms > 0 else -60.0
        rms_db = max(-60.0, min(0.0, rms_db))

        # Frame-based VAD and F0
        frame_len = int(sample_rate * FRAME_MS / 1000)
        hop_len = int(sample_rate * HOP_MS / 1000)
        if frame_len < 2 or hop_len < 1:
            return _response(seq, t_ms, rms_db, 0.0, 0.0, 0.0, 0.0, 0.0)

        n_frames = max(1, (len(sig) - frame_len) // hop_len + 1)
        frame_energies = []
        f0_list = []

        min_period = max(2, int(sample_rate / F0_MAX_HZ))
        max_period = min(frame_len // 2, int(sample_rate / F0_MIN_HZ))

        for i in range(n_frames):
            start = i * hop_len
            end = start + frame_len
            if end > len(sig):
                break
            frame = sig[start:end]
            energy = float(np.sqrt(np.mean(frame * frame)) + RMS_FLOOR)
            frame_energies.append(energy)

            # F0 via autocorrelation on voiced frames
            if energy > VOICED_THRESHOLD_RATIO and max_period > min_period:
                f0_hz = _estimate_f0_autocorr(frame, sample_rate, min_period, max_period)
                if f0_hz and F0_MIN_HZ <= f0_hz <= F0_MAX_HZ:
                    f0_list.append(f0_hz)

        # Voiced ratio: fraction of frames above threshold
        max_energy = max(frame_energies) if frame_energies else RMS_FLOOR
        threshold = max(VOICED_THRESHOLD_RATIO * max_energy, RMS_FLOOR * 2)
        voiced_frames = sum(1 for e in frame_energies if e >= threshold)
        voiced_ratio = voiced_frames / n_frames if n_frames else 0.0
        voiced_ratio = max(0.0, min(1.0, voiced_ratio))

        # F0 mean and std (over voiced frames only)
        if f0_list:
            f0_mean = float(np.mean(f0_list))
            f0_std = float(np.std(f0_list))
        else:
            f0_mean = 0.0
            f0_std = 0.0

        # Intonation proxy: 0-1 from F0 std (e.g. 0-50 Hz -> 0-1, band-pass so middle is good)
        # Monotone (0 std) -> 0; very chaotic (high std) -> cap at 1. Sweet spot ~15-25 Hz.
        if f0_std <= 0:
            intonation_proxy = 0.0
        else:
            # Normalize: 25 Hz std ~ 0.5, 50 Hz -> 1.0
            intonation_proxy = min(1.0, f0_std / 50.0)

        # Pace proxy: voiced_ratio as proxy for "activity" (more voice = faster pace)
        pace_proxy = max(0.0, min(1.0, voiced_ratio * 1.2))  # slight scale

        return _response(
            seq, t_ms, rms_db, voiced_ratio,
            f0_mean, f0_std, intonation_proxy, pace_proxy,
        )
    except Exception:
        return _empty_response(seq, t_ms)


def _estimate_f0_autocorr(
    frame: np.ndarray,
    sample_rate: int,
    min_period: int,
    max_period: int,
) -> Optional[float]:
    """Autocorrelation pitch estimation. Returns F0 in Hz or None."""
    if frame.size < max_period * 2:
        return None
    frame = frame - np.mean(frame)
    corr = np.correlate(frame, frame, mode="full")
    mid = len(corr) // 2
    # Search only positive lags (second half)
    search = corr[mid + min_period : mid + max_period + 1]
    if search.size == 0:
        return None
    peak_idx = np.argmax(search)
    lag = min_period + peak_idx
    if lag <= 0:
        return None
    return float(sample_rate) / float(lag)


def _response(
    seq: int,
    t_ms: int,
    rms_db: float,
    voiced_ratio: float,
    f0_hz_mean: float,
    f0_hz_std: float,
    intonation_proxy: float,
    pace_proxy: float,
) -> dict:
    return {
        "seq": seq,
        "t_ms": t_ms,
        "rms_db": round(rms_db, 1),
        "voiced_ratio": round(voiced_ratio, 2),
        "f0_hz_mean": round(f0_hz_mean, 1),
        "f0_hz_std": round(f0_hz_std, 1),
        "intonation_proxy": round(intonation_proxy, 2),
        "pace_proxy": round(pace_proxy, 2),
    }


def _empty_response(seq: int, t_ms: int) -> dict:
    return _response(seq, t_ms, -60.0, 0.0, 0.0, 0.0, 0.0, 0.0)
