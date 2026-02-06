"""
Real-time audio metrics for Ambient Glow (stateless).
Input: PCM16 mono, 16 kHz preferred (48k/44.1k resampled to 16k internally).
Output: raw + lightly normalized features for frontend to smooth (EMA + rolling window).
"""
import math
from typing import Optional

import numpy as np

# Target sample rate for processing (F0 and frame logic assume this)
TARGET_SAMPLE_RATE = 16000
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
# Ideal pause ratio (15–20% silence); used for pause_balance score
IDEAL_PAUSE_RATIO = 0.175
# How far from ideal (in ratio units) before score drops to 0
PAUSE_BALANCE_TOLERANCE = 0.35


def _resample_to_16k(sig: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample to TARGET_SAMPLE_RATE using linear interpolation. Returns float32."""
    if sample_rate <= 0 or sig.size == 0:
        return sig
    if sample_rate == TARGET_SAMPLE_RATE:
        return sig
    num_out = int(round(sig.size * TARGET_SAMPLE_RATE / sample_rate))
    if num_out <= 0:
        return sig
    indices = np.linspace(0, sig.size - 1, num=num_out, dtype=np.float32)
    return np.interp(indices, np.arange(sig.size, dtype=np.float32), sig.astype(np.float32)).astype(np.float32)


def process_pcm_chunk(
    pcm_bytes: bytes,
    sample_rate: int,
    seq: int = 0,
    t_ms: int = 0,
) -> dict:
    """
    Process one chunk of PCM16 little-endian mono audio.
    If sample_rate is not 16000 (e.g. 48000 or 44100), resamples to 16 kHz internally.
    Returns raw + lightly normalized features for frontend smoothing.

    Args:
        pcm_bytes: Raw PCM16 LE bytes (2 bytes per sample).
        sample_rate: Sample rate in Hz (16000, 48000, 44100, or 8000–48000).
        seq: Chunk sequence number (echoed in response).
        t_ms: Client timestamp or sample offset in ms (echoed in response).

    Returns:
        Dict with: seq, t_ms, rms_db, voiced_ratio, pause_balance, f0_hz_mean, f0_hz_std,
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
        # Resample to 16 kHz if needed (e.g. 48k or 44.1k from browser)
        if sample_rate != TARGET_SAMPLE_RATE:
            sig = _resample_to_16k(sig, sample_rate)
            sample_rate = TARGET_SAMPLE_RATE

        # RMS and dB
        rms = float(np.sqrt(np.mean(sig * sig)) + RMS_FLOOR)
        rms_db = 20.0 * math.log10(rms) if rms > 0 else -60.0
        rms_db = max(-60.0, min(0.0, rms_db))

        # Frame-based VAD and F0
        frame_len = int(sample_rate * FRAME_MS / 1000)
        hop_len = int(sample_rate * HOP_MS / 1000)
        if frame_len < 2 or hop_len < 1:
            return _response(seq, t_ms, rms_db, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

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

        # Pause balance: 0–1 score. Ideal pause ratio is 15–20% (silence); score = 1 when close to ideal.
        pause_ratio = 1.0 - voiced_ratio
        distance = abs(pause_ratio - IDEAL_PAUSE_RATIO)
        pause_balance = max(0.0, min(1.0, 1.0 - distance / PAUSE_BALANCE_TOLERANCE))

        return _response(
            seq, t_ms, rms_db, voiced_ratio, pause_balance,
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
    pause_balance: float,
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
        "pause_balance": round(pause_balance, 2),
        "f0_hz_mean": round(f0_hz_mean, 1),
        "f0_hz_std": round(f0_hz_std, 1),
        "intonation_proxy": round(intonation_proxy, 2),
        "pace_proxy": round(pace_proxy, 2),
    }


def _empty_response(seq: int, t_ms: int) -> dict:
    return _response(seq, t_ms, -60.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
