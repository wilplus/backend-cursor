"""
Compute speech metrics from raw audio bytes (webm/any format → PCM via ffmpeg).

Metrics: WPM, pause_ms, dynamic_db, emphasis_per_min, energy_ratio, pitch_center_st.
Used by recording_1_job (automatic) and backfill script.
"""
import logging
import math
import os
import subprocess
import shutil
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


def _resolve_ffmpeg_executable() -> Optional[str]:
    """Resolve ffmpeg: FFMPEG_PATH env, then PATH, then bundled imageio-ffmpeg."""
    env_path = (os.environ.get("FFMPEG_PATH") or "").strip()
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled:
            logger.warning("ffmpeg not found on PATH; using bundled imageio-ffmpeg binary")
            return bundled
    except Exception as e:
        logger.warning("ffmpeg fallback resolution failed: %s", e)
    return None


def decode_audio_to_pcm(audio_bytes: bytes) -> Optional[np.ndarray]:
    """Decode webm/any audio → 16kHz mono float32 PCM via ffmpeg."""
    ffmpeg_exe = _resolve_ffmpeg_executable()
    if not ffmpeg_exe:
        logger.warning("ffmpeg not found (PATH and bundled fallback unavailable)")
        return None
    try:
        proc = subprocess.run(
            [
                ffmpeg_exe, "-i", "pipe:0",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE), "-ac", "1",
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            logger.warning("ffmpeg decode failed returncode=%d stderr=%s", proc.returncode, proc.stderr[:500].decode("utf-8", errors="replace"))
            return None
        raw = proc.stdout
        if len(raw) < 2:
            return None
        samples = np.frombuffer(raw, dtype=np.int16)
        return samples.astype(np.float32) / 32768.0
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
    if sig is None:
        logger.warning("analyze_audio: decode_audio_to_pcm returned None (ffmpeg failed or not installed) audio_bytes=%d", len(audio_bytes) if audio_bytes else 0)
        return None
    return _analyze_pcm(sig, transcript=transcript, duration_sec=duration_sec, fallback_wpm=fallback_wpm)


def analyze_audio_window(
    audio_bytes: bytes,
    *,
    start_offset_ms: int,
    duration_ms: int,
    transcript: str = "",
) -> Optional[Dict]:
    """Slice the parent audio by [start, start+duration] and analyze ONLY that window.

    This is the single source of truth for "compute metrics for the
    exact time-bound slice of a snippet" — used by initial extraction
    AND by every boundary-adjust path (POST /boundaries, PATCH
    /admin/snippets/<id>) so the JSONB ``metrics`` blob on the snippet
    row always reflects the current window, not the parent recording.

    ``start_offset_ms`` and ``duration_ms`` are the same fields stored
    on the snippet row — pass them through verbatim.

    When ``transcript`` is empty we leave WPM as None. Callers that
    want a window-accurate WPM should re-Whisper the slice first
    (see ``extract_window_as_wav``) and pass the new transcript in.

    Returns None on decode failure or if the sliced window is too
    short for stable analysis (< 1s of PCM).
    """
    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None:
        logger.warning(
            "analyze_audio_window: decode_audio_to_pcm returned None "
            "(ffmpeg failed) bytes=%d",
            len(audio_bytes) if audio_bytes else 0,
        )
        return None

    sliced = _slice_pcm(sig, start_offset_ms, duration_ms)
    if sliced is None:
        return None

    duration_sec = len(sliced) / float(SAMPLE_RATE)
    return _analyze_pcm(sliced, transcript=transcript, duration_sec=duration_sec)


def extract_window_as_wav(
    audio_bytes: bytes,
    *,
    start_offset_ms: int,
    duration_ms: int,
) -> Optional[bytes]:
    """Decode the parent audio, slice to the window, wrap as WAV bytes.

    Used by recompute paths that need to re-transcribe just the
    sliced window via Whisper. WAV (16-bit PCM, 16 kHz mono) is
    universally accepted by the Whisper API and matches the
    sample-rate we already decode to, so there's no extra
    re-sampling step.
    """
    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None:
        return None

    sliced = _slice_pcm(sig, start_offset_ms, duration_ms)
    if sliced is None:
        return None

    return _pcm_to_wav_bytes(sliced)


def _slice_pcm(
    sig: "np.ndarray",
    start_offset_ms: int,
    duration_ms: int,
) -> Optional["np.ndarray"]:
    """Cut a [start, start+duration] window out of a decoded PCM
    array. Returns None when the resulting slice is too short
    (< 1 s) for the analysis pipeline to produce stable metrics.

    Bounds are clamped to the parent length so out-of-range offsets
    quietly truncate rather than throwing — the caller has no clean
    way to recover from a half-bad window other than to bail.
    """
    total_samples = len(sig)
    start_sample = max(0, int(start_offset_ms / 1000.0 * SAMPLE_RATE))
    start_sample = min(start_sample, total_samples)
    end_sample = max(
        start_sample,
        int((start_offset_ms + duration_ms) / 1000.0 * SAMPLE_RATE),
    )
    end_sample = min(end_sample, total_samples)
    sliced = sig[start_sample:end_sample]
    if len(sliced) < SAMPLE_RATE:
        logger.warning(
            "_slice_pcm: window too short (%d samples < %d) "
            "start_ms=%d duration_ms=%d parent_samples=%d",
            len(sliced), SAMPLE_RATE, start_offset_ms, duration_ms,
            total_samples,
        )
        return None
    return sliced


def _analyze_pcm(
    sig: "np.ndarray",
    *,
    transcript: str = "",
    duration_sec: float = 0.0,
    fallback_wpm: Optional[float] = None,
) -> Optional[Dict]:
    """Run the full metric suite on an already-decoded PCM array.

    Shared between ``analyze_audio`` (whole-file) and
    ``analyze_audio_window`` (sliced) so the metric definitions live
    in exactly one place. The signature matches what callers had
    when this was inlined in ``analyze_audio``.
    """
    if len(sig) < SAMPLE_RATE:
        logger.warning(
            "_analyze_pcm: audio too short (%d samples < %d) — skipping metrics",
            len(sig), SAMPLE_RATE,
        )
        return None

    if duration_sec <= 0:
        duration_sec = len(sig) / float(SAMPLE_RATE)

    dbs = _frame_rms_db(sig)
    voiced_mask = dbs >= SILENCE_DB_THRESHOLD
    voiced_dur = float(np.sum(voiced_mask)) * (FRAME_MS / 1000.0)

    # WPM from transcript.
    wpm: Optional[float] = None
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


def _pcm_to_wav_bytes(sig: "np.ndarray") -> bytes:
    """Wrap a 16 kHz mono float32 PCM array as a WAV blob.

    Whisper accepts WAV directly; this avoids an ffmpeg re-encode
    just to convert the slice back to a container format. We clip
    to [-1, 1] before quantising to int16 to dodge wrap-around on
    rare hot frames.
    """
    import io
    import wave

    clipped = np.clip(sig, -1.0, 1.0)
    int16 = (clipped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(SAMPLE_RATE)
        w.writeframes(int16.tobytes())
    return buf.getvalue()
