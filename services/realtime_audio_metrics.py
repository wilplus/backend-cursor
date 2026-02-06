"""
Real-time audio metrics for Ambient Glow (stateless).
Mathematical contract: raw measurement → ideal band → score [0,1] + delta [-1,+1].
Input: PCM16 mono, 16 kHz preferred (48k/44.1k resampled to 16k internally).
Output: seq, voiced_ratio, pacing_score/delta, intonation_score/delta, pause_score/delta.
Silence gating: when voiced_ratio < 0.15, return neutral (all score=1, delta=0).
"""
import math
from typing import Optional, Tuple

import numpy as np

TARGET_SAMPLE_RATE = 16000
F0_MIN_HZ = 60
F0_MAX_HZ = 350
FRAME_MS = 20
HOP_MS = 10
RMS_FLOOR = 1e-8
SILENCE_DB = -45.0
VOICED_RATIO_GATE = 0.15

# Band centers and radii (good zone = center ± radius)
PAUSE_CENTER = 0.20
PAUSE_RADIUS = 0.12
INTON_CENTER_CENTS = 70.0
INTON_RADIUS_CENTS = 50.0
PACE_CENTER_WPM = 145.0
PACE_RADIUS_WPM = 30.0
# Syllables per word for WPM proxy
SYLLABLES_PER_WORD = 1.3


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _smoothstep(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def band_score_and_delta(x: float, center: float, radius: float) -> Tuple[float, float]:
    """
    Signed delta in [-1, 1]; score in [0, 1] via smoothstep(1 - |delta|).
    Both extremes are bad; middle (good zone) gives score near 1.
    """
    if radius <= 0:
        return 1.0, 0.0
    delta = _clamp((x - center) / radius, -1.0, 1.0)
    raw_score = 1.0 - abs(delta)
    score = _smoothstep(raw_score)
    return score, delta


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
    return np.interp(
        indices, np.arange(sig.size, dtype=np.float32), sig.astype(np.float32)
    ).astype(np.float32)


def _frame_rms_db(x: np.ndarray, frame_size: int, hop: int) -> np.ndarray:
    """Per-frame RMS in dB."""
    rms_db_list = []
    for i in range(0, len(x) - frame_size + 1, hop):
        frame = x[i : i + frame_size]
        rms = math.sqrt(float(np.mean(frame * frame)) + RMS_FLOOR)
        db = 20.0 * math.log10(rms + RMS_FLOOR)
        rms_db_list.append(db)
    return np.array(rms_db_list, dtype=np.float32) if rms_db_list else np.array([], dtype=np.float32)


def _estimate_f0_autocorr(frame: np.ndarray, sr: int) -> Optional[float]:
    """Simple autocorrelation pitch. Returns F0 in Hz or None."""
    frame = frame - np.mean(frame)
    if np.max(np.abs(frame)) < 1e-3:
        return None
    corr = np.correlate(frame, frame, mode="full")
    mid = len(corr) // 2
    lag_min = int(sr / F0_MAX_HZ)
    lag_max = int(sr / F0_MIN_HZ)
    if lag_max <= lag_min + 2 or mid + lag_max >= len(corr):
        return None
    seg = corr[mid + lag_min : mid + lag_max + 1]
    lag = lag_min + int(np.argmax(seg))
    if lag <= 0:
        return None
    return float(sr) / float(lag)


def _count_envelope_peaks(x: np.ndarray, sr: int) -> int:
    """Envelope + peak count as syllable-rate proxy. Min distance between peaks to avoid double-count."""
    env = np.abs(x)
    win = int(0.03 * sr)
    if win < 3:
        return 0
    kernel = np.ones(win) / win
    env_smooth = np.convolve(env, kernel, mode="same")
    thr = float(np.percentile(env_smooth, 75))
    min_samples_between_peaks = int(0.08 * sr)  # ~80 ms minimum between peaks
    peaks = 0
    last_peak_i = -min_samples_between_peaks - 1
    for i in range(1, len(env_smooth) - 1):
        if (
            env_smooth[i] > thr
            and env_smooth[i] > env_smooth[i - 1]
            and env_smooth[i] > env_smooth[i + 1]
            and (i - last_peak_i) >= min_samples_between_peaks
        ):
            peaks += 1
            last_peak_i = i
    return peaks


def process_pcm_chunk(
    pcm_bytes: bytes,
    sample_rate: int,
    seq: int = 0,
    t_ms: int = 0,
    include_debug: bool = False,
) -> dict:
    """
    Process one chunk of PCM16 little-endian mono audio.
    Returns: seq, t_ms, voiced_ratio, pacing_score, pacing_delta, intonation_score,
             intonation_delta, pause_score, pause_delta.
    When voiced_ratio < VOICED_RATIO_GATE (0.15), returns neutral (all score=1, delta=0).
    If include_debug is True, adds raw debug fields: silence_ratio, std_cents, wpm_proxy.
    """
    if len(pcm_bytes) < 2:
        return _neutral_response(seq, t_ms, 0.0, include_debug)

    try:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if samples.size == 0:
            return _neutral_response(seq, t_ms, 0.0, include_debug)
        sig = samples.astype(np.float32) / 32768.0

        if sample_rate != TARGET_SAMPLE_RATE:
            sig = _resample_to_16k(sig, sample_rate)
            sample_rate = TARGET_SAMPLE_RATE

        frame_size = int(FRAME_MS * sample_rate / 1000)
        hop = int(HOP_MS * sample_rate / 1000)
        if frame_size < 2 or hop < 1:
            return _neutral_response(seq, t_ms, 0.0, include_debug)

        # VAD: frame RMS dB
        dbs = _frame_rms_db(sig, frame_size, hop)
        voiced = dbs > SILENCE_DB
        n_frames = len(voiced)
        voiced_ratio = float(np.mean(voiced)) if n_frames else 0.0
        voiced_ratio = max(0.0, min(1.0, voiced_ratio))

        # Silence gating: neutral so UI doesn't punish pauses
        if voiced_ratio < VOICED_RATIO_GATE:
            return _neutral_response(seq, t_ms, voiced_ratio, include_debug)

        chunk_seconds = len(sig) / float(sample_rate)

        # --- Pause: silence_ratio band ---
        silence_ratio = 1.0 - voiced_ratio
        pause_score, pause_delta = band_score_and_delta(
            silence_ratio, PAUSE_CENTER, PAUSE_RADIUS
        )

        # --- Intonation: pitch std in cents ---
        f0s = []
        for i in range(n_frames):
            if not voiced[i]:
                continue
            start = i * hop
            end = start + frame_size
            if end > len(sig):
                break
            frame = sig[start:end]
            f0 = _estimate_f0_autocorr(frame, sample_rate)
            if f0 is not None and F0_MIN_HZ <= f0 <= F0_MAX_HZ:
                f0s.append(f0)

        if len(f0s) < 3:
            intonation_score, intonation_delta = 1.0, 0.0
            std_cents = 0.0
        else:
            f0s_arr = np.array(f0s, dtype=np.float32)
            med = float(np.median(f0s_arr))
            med = max(med, 1e-6)
            cents = 1200.0 * np.log2(f0s_arr / med)
            std_cents = float(np.std(cents))
            intonation_score, intonation_delta = band_score_and_delta(
                std_cents, INTON_CENTER_CENTS, INTON_RADIUS_CENTS
            )

        # --- Pacing: envelope peaks → WPM proxy ---
        peaks = _count_envelope_peaks(sig, sample_rate)
        peaks_per_sec = peaks / max(chunk_seconds, 1e-6)
        wpm_proxy = (peaks_per_sec * 60.0) / SYLLABLES_PER_WORD
        pacing_score, pacing_delta = band_score_and_delta(
            wpm_proxy, PACE_CENTER_WPM, PACE_RADIUS_WPM
        )

        out = {
            "seq": seq,
            "t_ms": t_ms,
            "voiced_ratio": round(voiced_ratio, 2),
            "pacing_score": round(float(pacing_score), 2),
            "pacing_delta": round(float(pacing_delta), 2),
            "intonation_score": round(float(intonation_score), 2),
            "intonation_delta": round(float(intonation_delta), 2),
            "pause_score": round(float(pause_score), 2),
            "pause_delta": round(float(pause_delta), 2),
        }
        if include_debug:
            out["_debug"] = {
                "silence_ratio": round(silence_ratio, 2),
                "std_cents": round(std_cents, 1) if len(f0s) >= 3 else None,
                "wpm_proxy": round(wpm_proxy, 1),
            }
        return out
    except Exception:
        return _neutral_response(seq, t_ms, 0.0, include_debug)


def _neutral_response(
    seq: int, t_ms: int, voiced_ratio: float, include_debug: bool
) -> dict:
    """Return when chunk is empty or silence-gated (voiced_ratio < gate)."""
    out = {
        "seq": seq,
        "t_ms": t_ms,
        "voiced_ratio": round(max(0.0, min(1.0, voiced_ratio)), 2),
        "pacing_score": 1.0,
        "pacing_delta": 0.0,
        "intonation_score": 1.0,
        "intonation_delta": 0.0,
        "pause_score": 1.0,
        "pause_delta": 0.0,
    }
    if include_debug:
        out["_debug"] = {"silence_ratio": None, "std_cents": None, "wpm_proxy": None}
    return out
