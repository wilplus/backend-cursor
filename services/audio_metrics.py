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

# ── Snippet segmentation (willab Readout multi-snippet, design §5/§14) ─
# Carve one recording into multiple "moment" windows at silence
# boundaries, so the Readout can show "Snippet 2 of 5" instead of one
# whole-recording snippet. See segment_into_snippets().
SEGMENT_MAX_SNIPPETS = 10    # §14 top-N cap (~10) — bounds coach load
SEGMENT_MIN_SEC = 3.0        # shorter than this isn't a meaningful moment
SEGMENT_MAX_SEC = 8.0       # split longer monologues into chunks
SEGMENT_GAP_SEC = 0.6        # silence ≥ this delimits a snippet boundary
                             # (longer than a within-utterance MIN_PAUSE_SEC)
SEGMENT_PAD_SEC = 0.2        # natural-playback padding each side


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


def compress_audio_for_whisper(audio_bytes: bytes) -> Optional[bytes]:
    """Transcode any audio → 16kHz mono mp3 (speech-optimal, small) so a long
    recording fits under OpenAI Whisper's 25MB upload cap.

    Whisper only needs intelligible speech, so 16kHz mono @48kbps is plenty
    (~0.36 MB/min → ~70 min under 25MB). The acoustic pipeline keeps using the
    FULL-quality original; only the transcription copy is compressed. Returns
    the mp3 bytes, or None on failure (caller falls back to the original)."""
    ffmpeg_exe = _resolve_ffmpeg_executable()
    if not ffmpeg_exe:
        return None
    try:
        proc = subprocess.run(
            [
                ffmpeg_exe, "-i", "pipe:0",
                "-ac", "1", "-ar", str(SAMPLE_RATE), "-b:a", "48k",
                "-f", "mp3", "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0 or not proc.stdout:
            logger.warning(
                "compress_audio_for_whisper: ffmpeg rc=%d stderr=%s",
                proc.returncode, proc.stderr[:300].decode("utf-8", "replace"),
            )
            return None
        return proc.stdout
    except Exception as e:
        logger.warning("compress_audio_for_whisper error: %s", e)
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


def _compute_f0_series(sig: np.ndarray) -> list:
    """Per-window fundamental-frequency (Hz) series in temporal order.

    Autocorrelation pitch estimate per PITCH_WINDOW; only confident
    windows (peak ≥ PITCH_CONFIDENCE_THRESHOLD) are kept. The single
    source of truth for every F0-derived feature (center, mean, SD,
    slope, mid-vs-end delta) so they're all computed from one pass.
    """
    min_lag = int(SAMPLE_RATE / PITCH_MAX_HZ)
    max_lag = int(SAMPLE_RATE / PITCH_MIN_HZ)
    pitch_hz_list: list = []
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
    return _reject_octave_outliers(pitch_hz_list)


def _reject_octave_outliers(series: list) -> list:
    """Drop octave-error frames from a bare-autocorrelation F0 series.

    The estimator picks a sub-/super-harmonic on some frames (≈2x or 0.5x
    the true pitch). The median is robust to these, but they wreck f0_sd
    (and f0_slope) — e.g. an honest ~30 Hz SD blows up to 100+ Hz. So we
    reject any frame more than ~0.6 octave (≈1.5x) from the median; octave
    jumps sit a full octave out and are removed, while genuine expressive
    variation (well under half an octave frame-to-frame for speech) stays.

    Conservative + None-safe; needs ≥4 frames to act, and never returns
    fewer than 2 (falls back to the raw series if it would over-prune).
    NOTE: the 0.6-octave threshold is a sane default — eyeball it against a
    real recording before treating f0_sd as precise.
    """
    if len(series) < 4:
        return series
    med = float(np.median(series))
    if med <= 0:
        return series
    kept = [f for f in series if f > 0 and abs(math.log2(f / med)) <= 0.6]
    return kept if len(kept) >= 2 else series


def _pitch_center_st_from_series(series: list) -> Tuple[Optional[float], int]:
    """Median F0 → semitones (the legacy pitch_center_st), from a
    pre-computed F0 series."""
    if not series:
        return None, 0
    median_hz = float(np.median(series))
    semitones = 12.0 * math.log2(median_hz / PITCH_REF_HZ)
    return round(semitones, 1), len(series)


def _compute_pitch_center_st(sig: np.ndarray) -> Tuple[Optional[float], int]:
    """Back-compat wrapper for external callers — recomputes the F0
    series. In-pipeline (_analyze_pcm) the series is computed once and
    shared, so this isn't called there."""
    return _pitch_center_st_from_series(_compute_f0_series(sig))


def _compute_f0_stats(
    series: list,
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Readout F0 features from the F0 series, all in Hz / Hz-per-sec:

      f0_mean          — mean fundamental frequency (Hz)
      f0_sd            — its standard deviation (expressive pitch range)
      f0_slope         — linear trend over the snippet (Hz/sec; + rising,
                         - falling). The "does the voice lift or drop"
                         dynamic.
      f0_mid_end_delta — mean(middle third) − mean(last third) of the
                         contour (Hz). Captures the question-uptick /
                         trail-off pattern at sentence ends.

    Each is None when the series is too short to be meaningful.
    Approximation note (v1): slope/delta index the *confident-window*
    series, so silent gaps compress; good enough for a relative read,
    not absolute prosody timing.
    """
    if not series:
        return (None, None, None, None)
    arr = np.array(series, dtype=np.float32)

    f0_mean = round(float(arr.mean()), 1)
    f0_sd = round(float(arr.std()), 1) if len(arr) >= 2 else None

    f0_slope: Optional[float] = None
    f0_mid_end_delta: Optional[float] = None
    if len(arr) >= 3:
        hop_sec = PITCH_WINDOW / float(SAMPLE_RATE)
        x = np.arange(len(arr), dtype=np.float32) * hop_sec
        f0_slope = round(float(np.polyfit(x, arr, 1)[0]), 2)  # Hz/sec
        third = len(arr) // 3
        mid = arr[third : 2 * third]
        end = arr[2 * third :]
        if len(mid) and len(end):
            f0_mid_end_delta = round(float(mid.mean() - end.mean()), 1)

    return (f0_mean, f0_sd, f0_slope, f0_mid_end_delta)


def _pause_runs_ms(dbs: np.ndarray) -> list:
    """Durations (ms) of every qualifying silence run (≥ MIN_PAUSE_SEC).
    Shared by pause_ratio + pause_regularity."""
    is_silent = dbs < SILENCE_DB_THRESHOLD
    min_frames = int(MIN_PAUSE_SEC * 1000 / FRAME_MS)
    runs: list = []
    run_len = 0
    for s in is_silent:
        if s:
            run_len += 1
        else:
            if run_len >= min_frames:
                runs.append(run_len * FRAME_MS)
            run_len = 0
    if run_len >= min_frames:
        runs.append(run_len * FRAME_MS)
    return runs


def _compute_pause_ratio(dbs: np.ndarray) -> Optional[float]:
    """Fraction of the snippet spent in qualifying pauses (0..1).
    The Readout hero "32% paused"."""
    if len(dbs) == 0:
        return None
    total_ms = len(dbs) * FRAME_MS
    if total_ms <= 0:
        return None
    pause_total_ms = sum(_pause_runs_ms(dbs))
    return round(pause_total_ms / total_ms, 3)


def _compute_pause_regularity(dbs: np.ndarray) -> Optional[float]:
    """Regularity of pause durations in (0, 1]: 1.0 = perfectly even
    pacing, lower = erratic. Bounded inverse of the coefficient of
    variation. None when there are fewer than 2 pauses (regularity is
    undefined for one pause)."""
    runs = _pause_runs_ms(dbs)
    if len(runs) < 2:
        return None
    arr = np.array(runs, dtype=np.float32)
    mean = float(arr.mean())
    if mean <= 0:
        return None
    cv = float(arr.std()) / mean
    return round(1.0 / (1.0 + cv), 3)


def _compute_intensity_envelope(dbs: np.ndarray) -> Optional[float]:
    """Slope of the voiced-loudness contour (dB/sec). + = builds toward
    the end, - = fades. A scalar v1 read of "intensity-envelope shape".
    None when too few voiced frames."""
    voiced = dbs[dbs >= SILENCE_DB_THRESHOLD]
    if len(voiced) < 5:
        return None
    x = np.arange(len(voiced), dtype=np.float32) * (FRAME_MS / 1000.0)
    slope = float(np.polyfit(x, voiced.astype(np.float32), 1)[0])
    return round(slope, 3)


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


def analyze_pcm_window(
    sig: "np.ndarray",
    *,
    start_offset_ms: int,
    duration_ms: int,
    transcript: str = "",
) -> Optional[Dict]:
    """Analyze a window of an ALREADY-DECODED PCM array.

    The multi-snippet extraction path decodes the parent recording ONCE
    (for segmentation) and then calls this per segment — avoiding the N
    re-decodes that ``analyze_audio_window`` (bytes → decode → slice)
    would incur when carving one recording into many snippets.

    Returns the metrics dict for the slice, or None when the window is
    too short (< 1s) for stable analysis.
    """
    if sig is None:
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

    # F0 series computed once, shared by every pitch-derived feature.
    f0_series = _compute_f0_series(sig)
    pitch_st, pitch_frames = _pitch_center_st_from_series(f0_series)
    f0_mean, f0_sd, f0_slope, f0_mid_end_delta = _compute_f0_stats(f0_series)

    # Time-based voiced ratio (voiced frames / total frames) — the
    # Readout's "voiced_ratio". Distinct from energy_ratio (voiced
    # energy / total energy), kept below for back-compat.
    voiced_ratio = (
        round(float(np.sum(voiced_mask)) / len(dbs), 3) if len(dbs) else None
    )

    result = {
        "wpm": wpm,
        "pause_ms": _compute_pause_ms(dbs),
        "dynamic_db": _compute_dynamic_db(dbs),
        "emphasis_per_min": _compute_emphasis_per_min(dbs, duration_sec),
        "energy_ratio": _compute_energy_ratio(sig, dbs),
        "pitch_center_st": pitch_st,
        "pitch_frame_count": pitch_frames,
        "voiced_duration_sec": round(voiced_dur, 1),
        # ── willab Readout feature completion (the 6 missing + a true
        # voiced_ratio). Maps the 10-feature Readout set (design §5):
        #   f0_mean / f0_sd            ← here
        #   speech_rate                ← wpm (above)
        #   mean_pause                 ← pause_ms (above)
        #   pause_ratio                ← here
        #   loudness_range             ← dynamic_db (above)
        #   voiced_ratio               ← here (time-based)
        #   f0_slope                   ← here
        #   pause_regularity           ← here
        #   intensity_envelope         ← here
        #   f0_mid_end_delta           ← here
        "f0_mean": f0_mean,
        "f0_sd": f0_sd,
        "f0_slope": f0_slope,
        "f0_mid_end_delta": f0_mid_end_delta,
        "pause_ratio": _compute_pause_ratio(dbs),
        "pause_regularity": _compute_pause_regularity(dbs),
        "intensity_envelope": _compute_intensity_envelope(dbs),
        "voiced_ratio": voiced_ratio,
    }

    # ── Librosa feature block (additive) ──────────────────────────
    # Best-effort: if librosa is unavailable (import error) or the
    # analysis fails for any reason, we log and continue with the
    # existing metrics — the pipeline never breaks because of a
    # missing librosa feature. The new keys are absent from the
    # result dict when librosa fails, which is explicitly handled
    # by every downstream consumer that reads them.
    #
    # Features added and why each matters for the T:C classifier:
    #
    #   mfcc_mean (13 values) — Mel-frequency cepstral coefficients.
    #     Encode the overall spectral shape of the voice. The
    #     acoustic literature consistently shows MFCCs as the
    #     strongest single feature group for stress classification
    #     (Scherer 2003; Tahon & Devillers 2016). The 13 means are
    #     a compact but rich summary.
    #
    #   spectral_centroid_mean — "brightness" of the voice. Rises
    #     under threat-toned activation (voice becomes tenser, more
    #     high-frequency energy). Drops during relaxed, charismatic
    #     delivery where low-frequency resonance dominates.
    #
    #   spectral_rolloff_mean — frequency below which 85% of the
    #     spectral energy lives. Complements centroid; together they
    #     characterise the tonal quality of the voice.
    #
    #   zero_crossing_rate_mean (ZCR) — number of sign changes per
    #     frame. Correlates with unvoiced (fricative) content and
    #     breathiness. Elevated ZCR during stress reflects vocal
    #     tension and reduced breath support.
    #
    #   spectral_flux_mean — frame-to-frame spectral change rate.
    #     Measures how dynamic the delivery is. High flux = expressive,
    #     variable delivery (charisma signature). Low flux = monotone
    #     (stress/avoidance signature).
    #
    #   chroma_mean (12 values) — pitch class energy distribution.
    #     Encodes tonal coloring. Used as a cross-check for the
    #     autocorrelation pitch estimate; also captures melodic
    #     contour across the snippet.
    #
    # Storage: all values land in the snippet's metrics JSONB column
    # as new keys alongside the existing ones. NO migration needed —
    # charisma_snippets.metrics is JSONB (add_charisma_snippets_
    # metrics_column.sql) and accepts arbitrary new keys. A dedicated
    # columnar feature store can come later when the classifier is
    # trained (spec §11 training-annotation store); for the beta the
    # JSONB blob is the feature sink.
    try:
        librosa_features = _compute_librosa_features(sig)
        if librosa_features:
            result.update(librosa_features)
    except Exception as lib_err:
        logger.warning(
            "_analyze_pcm: librosa block failed (non-fatal) err=%s",
            lib_err,
        )

    return result


def _compute_librosa_features(sig: "np.ndarray") -> Optional[Dict]:
    """Compute librosa-derived features from 16 kHz mono float32 PCM.

    Returns a dict of new feature keys, or None when librosa is
    unavailable or the signal is too short. Never raises — callers
    are expected to swallow any exception from this function.

    All features are averaged across time (mean of per-frame values)
    so the output is a fixed-length flat dict regardless of the
    snippet duration. That keeps the metrics JSONB schema stable and
    directly feedable to a classifier without further aggregation.
    """
    try:
        import librosa
    except ImportError:
        logger.warning(
            "_compute_librosa_features: librosa not installed — "
            "add librosa>=0.10.0 to requirements.txt"
        )
        return None

    # Minimum signal length for stable STFT (at least 2 windows).
    if len(sig) < 2048:
        return None

    sr = SAMPLE_RATE  # 16 000 Hz — already decoded by ffmpeg

    try:
        # ── MFCCs: 13 coefficients, mean across time ───────────────
        mfccs = librosa.feature.mfcc(y=sig, sr=sr, n_mfcc=13)
        mfcc_mean = [round(float(v), 4) for v in mfccs.mean(axis=1)]

        # ── Spectral centroid ───────────────────────────────────────
        centroid = librosa.feature.spectral_centroid(y=sig, sr=sr)
        spectral_centroid_mean = round(float(centroid.mean()), 2)

        # ── Spectral rolloff (85th percentile) ─────────────────────
        rolloff = librosa.feature.spectral_rolloff(
            y=sig, sr=sr, roll_percent=0.85,
        )
        spectral_rolloff_mean = round(float(rolloff.mean()), 2)

        # ── Zero-crossing rate ──────────────────────────────────────
        zcr = librosa.feature.zero_crossing_rate(sig)
        zero_crossing_rate_mean = round(float(zcr.mean()), 6)

        # ── Spectral flux ───────────────────────────────────────────
        # librosa doesn't expose spectral_flux directly; we compute
        # it as the L2 norm of frame-to-frame STFT magnitude diffs.
        stft_mag = np.abs(librosa.stft(sig))
        flux_frames = np.sqrt(
            np.sum(np.diff(stft_mag, axis=1) ** 2, axis=0)
        )
        spectral_flux_mean = round(float(flux_frames.mean()), 4)

        # ── Chroma: 12 pitch class energies, mean across time ──────
        chroma = librosa.feature.chroma_stft(y=sig, sr=sr)
        chroma_mean = [round(float(v), 4) for v in chroma.mean(axis=1)]

        return {
            "mfcc_mean":               mfcc_mean,        # list[float] len 13
            "spectral_centroid_mean":  spectral_centroid_mean,  # Hz
            "spectral_rolloff_mean":   spectral_rolloff_mean,   # Hz
            "zero_crossing_rate_mean": zero_crossing_rate_mean,
            "spectral_flux_mean":      spectral_flux_mean,
            "chroma_mean":             chroma_mean,       # list[float] len 12
        }

    except Exception as e:
        logger.warning(
            "_compute_librosa_features: computation failed err=%s", e,
        )
        return None


def segment_into_snippets(
    sig: "np.ndarray",
    *,
    max_snippets: int = SEGMENT_MAX_SNIPPETS,
    min_snippet_sec: float = SEGMENT_MIN_SEC,
    max_snippet_sec: float = SEGMENT_MAX_SEC,
    gap_sec: float = SEGMENT_GAP_SEC,
    pad_sec: float = SEGMENT_PAD_SEC,
) -> list:
    """Carve a decoded PCM recording into snippet windows at silence
    boundaries (willab Readout multi-snippet, design §5).

    Returns a list of ``(start_ms, end_ms)`` windows in CHRONOLOGICAL
    order — the offsets the caller writes to each charisma_snippets row
    (the parent-audio + offset-window model the boundary-adjust path
    already uses). The caller runs ``analyze_audio_window`` per window
    for the per-snippet feature blob.

    Algorithm (VAD/pause based):
      1. Frame-level voice activity = RMS dB ≥ SILENCE_DB_THRESHOLD.
      2. Group voiced frames into segments, splitting wherever a silence
         run reaches ``gap_sec`` (a real "moment" boundary — longer than
         a within-utterance pause).
      3. Pad each window ±``pad_sec`` (natural playback), clamp to bounds.
      4. Drop windows shorter than ``min_snippet_sec``; split windows
         longer than ``max_snippet_sec`` into even sub-chunks.
      5. Rank by duration (a fuller, longer moment is more analyzable),
         cap to ``max_snippets`` (§14), return chronological.

    Fallbacks (never returns zero windows for a usable recording):
      - signal < 1s → ``[]`` (nothing to segment; caller skips).
      - no clear voiced segments, or every candidate too short → the
        whole recording as one window ``[(0, total_ms)]`` (preserves the
        legacy single-snippet behaviour as the floor).
    """
    if sig is None or len(sig) < SAMPLE_RATE:
        return []

    total_ms = int(len(sig) / SAMPLE_RATE * 1000)
    dbs = _frame_rms_db(sig)
    if len(dbs) == 0:
        return [(0, total_ms)]

    voiced = dbs >= SILENCE_DB_THRESHOLD
    gap_frames = max(1, int(gap_sec * 1000 / FRAME_MS))

    # ── Group voiced frames into raw segments split on long silences ──
    raw: list = []  # (start_frame, end_frame_exclusive)
    seg_start = None
    last_voiced = None
    silence_run = 0
    for i in range(len(voiced)):
        if voiced[i]:
            if seg_start is None:
                seg_start = i
            last_voiced = i
            silence_run = 0
        elif seg_start is not None:
            silence_run += 1
            if silence_run >= gap_frames:
                raw.append((seg_start, last_voiced + 1))
                seg_start = None
                silence_run = 0
    if seg_start is not None and last_voiced is not None:
        raw.append((seg_start, last_voiced + 1))

    if not raw:
        return [(0, total_ms)]

    # ── frames → ms, pad/clamp, enforce min/max duration ─────────────
    pad_ms = int(pad_sec * 1000)
    min_ms = int(min_snippet_sec * 1000)
    max_ms = int(max_snippet_sec * 1000)
    windows: list = []
    for (sf, ef) in raw:
        s_ms = max(0, sf * FRAME_MS - pad_ms)
        e_ms = min(total_ms, ef * FRAME_MS + pad_ms)
        dur = e_ms - s_ms
        if dur < min_ms:
            continue
        if dur <= max_ms:
            windows.append((s_ms, e_ms))
            continue
        # Split a long monologue into even sub-chunks ≤ max_ms.
        n_chunks = (dur + max_ms - 1) // max_ms
        chunk = dur // n_chunks
        for c in range(n_chunks):
            cs = s_ms + c * chunk
            ce = e_ms if c == n_chunks - 1 else min(e_ms, cs + chunk)
            if ce - cs >= min_ms:
                windows.append((cs, ce))

    if not windows:
        return [(0, total_ms)]

    # Rank by duration (analyzability proxy), cap to top-N, chronological.
    windows.sort(key=lambda w: (w[1] - w[0]), reverse=True)
    kept = windows[: max(1, max_snippets)]
    kept.sort(key=lambda w: w[0])
    return kept


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
