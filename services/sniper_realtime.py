"""
Sniper Wheel — real-time metrics from PCM.
Rolling 30s window for pause, dynamic (p95-p5), emphasis (+6 dB, 300 ms spacing).
Session-long buffer for energy thirds (normalized by session mean) and dramatic-pause check.
"""
import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

TARGET_SAMPLE_RATE = 16000
FRAME_MS = 20
HOP_MS = 20
RMS_FLOOR = 1e-8
SILENCE_DB_THRESHOLD = -45.0
VOICED_RATIO_GATE = 0.08
WINDOW_30_SEC = 30.0
WINDOW_3MIN_SEC = 180.0
MIN_VOICED_FOR_ENERGY_SEC = 120.0  # only compute thirds after ≥ 2 min voiced
EMPHASIS_BASELINE_SEC = 3.0
EMPHASIS_DB_ABOVE_BASELINE = 6.0
EMPHASIS_MIN_SPACING_SEC = 0.3
MIN_PAUSE_EVENT_SEC = 0.2
DRAMATIC_PAUSE_MIN_SEC = 1.5
EMPHASIS_SNR_MIN_DB = -50.0  # exclude frames below this from emphasis

_session_state: Dict[str, Dict] = {}


def _resample_to_16k(sig: np.ndarray, sample_rate: int) -> np.ndarray:
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
    rms_db_list = []
    for i in range(0, len(x) - frame_size + 1, hop):
        frame = x[i : i + frame_size]
        rms = math.sqrt(float(np.mean(frame * frame)) + RMS_FLOOR)
        db = 20.0 * math.log10(rms + RMS_FLOOR)
        rms_db_list.append(db)
    return np.array(rms_db_list, dtype=np.float32) if rms_db_list else np.array([], dtype=np.float32)


def _compute_pause_events(
    frames: List[Tuple[float, bool, float]],
) -> Tuple[float, float, int, float, bool]:
    """Returns (silent_time, window_time, num_events, max_pause_s, has_dramatic_pause)."""
    if not frames:
        return 0.0, 0.0, 0, 0.0, False
    frame_dur = FRAME_MS / 1000.0
    t_min = frames[0][0]
    t_max = frames[-1][0] + frame_dur
    window_time = t_max - t_min
    if window_time <= 0:
        window_time = frame_dur * len(frames)

    silent_time = 0.0
    num_events = 0
    max_pause_s = 0.0
    has_dramatic = False
    run_start = None

    for t_sec, is_silent, _ in frames:
        if is_silent:
            silent_time += frame_dur
            if run_start is None:
                run_start = t_sec
        else:
            if run_start is not None:
                run_dur = t_sec - run_start
                if run_dur >= MIN_PAUSE_EVENT_SEC:
                    num_events += 1
                    max_pause_s = max(max_pause_s, run_dur)
                    if run_dur >= DRAMATIC_PAUSE_MIN_SEC:
                        has_dramatic = True
                run_start = None
    if run_start is not None:
        run_dur = (frames[-1][0] + frame_dur) - run_start
        if run_dur >= MIN_PAUSE_EVENT_SEC:
            num_events += 1
            max_pause_s = max(max_pause_s, run_dur)
            if run_dur >= DRAMATIC_PAUSE_MIN_SEC:
                has_dramatic = True

    return silent_time, window_time, num_events, max_pause_s, has_dramatic


def _dynamic_range_p95_p5(rms_db_voiced: np.ndarray) -> Tuple[float, float, float]:
    """Returns (dynamic_range_db, p5, p95). If insufficient voiced frames, return (0, 0, 0)."""
    if rms_db_voiced.size < 10:
        return 0.0, 0.0, 0.0
    p5 = float(np.percentile(rms_db_voiced, 5))
    p95 = float(np.percentile(rms_db_voiced, 95))
    return p95 - p5, p5, p95


def _rms_instability(rms_db_voiced: np.ndarray, sub_window_frames: int = 50) -> float:
    """Rolling std of RMS over sub-windows; return max std (dB)."""
    if rms_db_voiced.size < sub_window_frames:
        return 0.0
    stds = []
    for i in range(0, rms_db_voiced.size - sub_window_frames + 1):
        stds.append(float(np.std(rms_db_voiced[i : i + sub_window_frames])))
    return max(stds) if stds else 0.0


def _emphasis_events(
    frames: List[Tuple[float, bool, float]],
    baseline_sec: float = EMPHASIS_BASELINE_SEC,
    db_above: float = EMPHASIS_DB_ABOVE_BASELINE,
    min_spacing_sec: float = EMPHASIS_MIN_SPACING_SEC,
) -> int:
    """
    True emphasis: RMS >= rolling baseline + db_above, voiced, SNR gate, merge within min_spacing.
    Returns count of merged events in window.
    """
    if len(frames) < 2:
        return 0
    frame_dur = FRAME_MS / 1000.0
    baseline_frames = int(baseline_sec / frame_dur)
    if baseline_frames < 1:
        baseline_frames = 1

    # Rolling baseline (mean RMS over last baseline_sec) for voiced frames only
    rms_voiced = []
    t_voiced = []
    for t_sec, is_silent, rms_db in frames:
        if not is_silent and rms_db > EMPHASIS_SNR_MIN_DB:
            rms_voiced.append(rms_db)
            t_voiced.append(t_sec)

    if len(rms_voiced) < baseline_frames:
        return 0

    # For each voiced frame, baseline = mean of preceding baseline_frames voiced RMS
    events = []
    for i in range(len(rms_voiced)):
        start = max(0, i - baseline_frames)
        baseline = float(np.mean(rms_voiced[start:i]))
        if rms_voiced[i] >= baseline + db_above:
            events.append(t_voiced[i])

    # Merge events within min_spacing_sec
    merged = 0
    last_t = -1000.0
    for t in events:
        if t - last_t >= min_spacing_sec:
            merged += 1
            last_t = t
    return merged


def _energy_thirds_normalized(
    frames: List[Tuple[float, bool, float]],
    session_start_sec: float,
    session_end_sec: float,
) -> Optional[Tuple[float, float, float, float, bool, bool]]:
    """
    E1, E2, E3 = mean RMS per third (voiced only), normalized by session mean.
    Returns (e1, e2, e3, session_mean_rms, has_recovery, is_declining) or None if < 2 min voiced.
    """
    if not frames or session_end_sec - session_start_sec < MIN_VOICED_FOR_ENERGY_SEC:
        return None
    frame_dur = FRAME_MS / 1000.0
    total_dur = session_end_sec - session_start_sec
    third = total_dur / 3.0
    t1_end = session_start_sec + third
    t2_end = session_start_sec + 2.0 * third

    rms_all = []
    rms_by_third: List[List[float]] = [[], [], []]
    for t_sec, is_silent, rms_db in frames:
        if is_silent:
            continue
        rms_linear = 10.0 ** (rms_db / 20.0)
        rms_all.append(rms_linear)
        if t_sec < t1_end:
            rms_by_third[0].append(rms_linear)
        elif t_sec < t2_end:
            rms_by_third[1].append(rms_linear)
        else:
            rms_by_third[2].append(rms_linear)

    if not rms_all:
        return None
    session_mean = float(np.mean(rms_all))
    if session_mean <= 0:
        return None

    e1 = float(np.mean(rms_by_third[0])) / session_mean if rms_by_third[0] else 1.0
    e2 = float(np.mean(rms_by_third[1])) / session_mean if rms_by_third[1] else 1.0
    e3 = float(np.mean(rms_by_third[2])) / session_mean if rms_by_third[2] else 1.0

    has_recovery = e3 >= e2
    is_declining = e2 > 0 and (e2 - e3) / e2 > 0.15

    return (e1, e2, e3, session_mean, has_recovery, is_declining)


def process_sniper_chunk(
    pcm_bytes: bytes,
    sample_rate: int,
    session_id: str,
    seq: int = 0,
    t_ms: int = 0,
    client_wpm: Optional[float] = None,
    include_debug: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Process one PCM chunk; update 30s and session buffers; return (sniper_inputs, debug).
    sniper_inputs is the dict to pass to sniper_scoring.compute_sniper_state().
    """
    debug: Dict[str, Any] = {}
    default_inputs = {
        "pace_wpm": client_wpm,
        "pace_variance_wpm": None,
        "pause_avg_ms": 440.0,
        "speech_density": 0.75,
        "max_pause_s": 0.0,
        "has_dramatic_pause": False,
        "dynamic_range_db": 14.0,
        "rms_instability_db": None,
        "emphasis_spikes_per_min": 35.0,
        "emphasis_monotone": False,
        "emphasis_front_loaded": False,
        "e1": None,
        "e2": None,
        "e3": None,
        "energy_has_recovery": False,
        "energy_is_declining": False,
    }

    if len(pcm_bytes) < 2:
        return default_inputs, {"reason": "empty_chunk", **debug}

    try:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if samples.size == 0:
            return default_inputs, {"reason": "empty_buffer", **debug}
        sig = samples.astype(np.float32) / 32768.0

        if sample_rate != TARGET_SAMPLE_RATE:
            sig = _resample_to_16k(sig, sample_rate)
            sample_rate = TARGET_SAMPLE_RATE

        frame_size = int(FRAME_MS * sample_rate / 1000)
        hop = int(HOP_MS * sample_rate / 1000)
        if frame_size < 2 or hop < 1:
            return default_inputs, {"reason": "invalid_frame", **debug}

        dbs = _frame_rms_db(sig, frame_size, hop)
        is_silent = dbs < SILENCE_DB_THRESHOLD
        n_frames = len(is_silent)
        voiced_ratio = float(np.mean(~is_silent)) if n_frames else 0.0
        voiced_ratio = max(0.0, min(1.0, voiced_ratio))

        if voiced_ratio < VOICED_RATIO_GATE:
            return default_inputs, {
                "reason": "silence_gated",
                "voiced_ratio": voiced_ratio,
                **debug,
            }

        chunk_dur_sec = len(sig) / float(sample_rate)
        frame_dur = FRAME_MS / 1000.0

        if session_id not in _session_state:
            _session_state[session_id] = {
                "next_t_sec": 0.0,
                "frames_30s": deque(maxlen=2000),
                "frames_session": deque(maxlen=30000),
            }
        state = _session_state[session_id]
        next_t = state["next_t_sec"]

        for i in range(n_frames):
            t_sec = next_t + i * frame_dur
            state["frames_30s"].append((t_sec, bool(is_silent[i]), float(dbs[i])))
            state["frames_session"].append((t_sec, bool(is_silent[i]), float(dbs[i])))

        next_t += chunk_dur_sec
        state["next_t_sec"] = next_t

        # Keep only last 30s in 30s buffer
        while state["frames_30s"] and state["frames_30s"][0][0] < next_t - WINDOW_30_SEC:
            state["frames_30s"].popleft()
        # Keep only last 3 min in session buffer (for energy we use full session; cap for memory)
        while state["frames_session"] and state["frames_session"][0][0] < next_t - WINDOW_3MIN_SEC:
            state["frames_session"].popleft()

        frames_30 = list(state["frames_30s"])
        frames_session = list(state["frames_session"])
        if not frames_30:
            return default_inputs, {"reason": "no_frames_30", **debug}

        # Pause (from 30s window)
        silent_time, window_time, num_events, max_pause_s, has_dramatic_30 = _compute_pause_events(frames_30)
        if window_time <= 0:
            pause_ratio = 0.0
            speech_density = 0.75
            avg_pause_ms = 440.0
        else:
            speech_density = 1.0 - (silent_time / window_time)
            speech_density = max(0.0, min(1.0, speech_density))
            pause_ratio = silent_time / window_time
            pauses_per_min = (num_events / window_time) * 60.0
            # Approx avg pause duration from ratio and event count
            if num_events > 0:
                avg_pause_s = silent_time / num_events
                avg_pause_ms = avg_pause_s * 1000.0
            else:
                avg_pause_ms = 440.0

        # Dramatic pause: check in last 3 min (use session buffer trimmed to 3 min)
        _, _, _, _, has_dramatic_pause = _compute_pause_events(frames_session)

        # Dynamic: p95 - p5 voiced RMS (30s)
        rms_voiced_30 = np.array([f[2] for f in frames_30 if not f[1]], dtype=np.float32)
        if rms_voiced_30.size > 0:
            dynamic_range_db, p5, p95 = _dynamic_range_p95_p5(rms_voiced_30)
            rms_instability_db = _rms_instability(rms_voiced_30)
        else:
            dynamic_range_db = 14.0
            p5 = p95 = 0.0
            rms_instability_db = None

        # Emphasis (30s): true events per minute
        emphasis_count = _emphasis_events(frames_30)
        voiced_dur_30 = window_time * (1.0 - pause_ratio) if window_time > 0 else 1.0
        if voiced_dur_30 > 0:
            emphasis_spikes_per_min = (emphasis_count / voiced_dur_30) * 60.0
        else:
            emphasis_spikes_per_min = 35.0

        # Energy thirds: only after ≥ 2 min voiced (addendum). Session start = oldest frame in buffer.
        voiced_frames_session = sum(1 for f in frames_session if not f[1])
        voiced_sec_session = voiced_frames_session * frame_dur
        session_start = state["frames_session"][0][0] if state["frames_session"] else next_t
        energy_result = (
            _energy_thirds_normalized(frames_session, session_start, next_t)
            if voiced_sec_session >= MIN_VOICED_FOR_ENERGY_SEC
            else None
        )

        if energy_result:
            e1, e2, e3, session_mean_rms, energy_has_recovery, energy_is_declining = energy_result
            debug["E1"] = round(e1, 4)
            debug["E2"] = round(e2, 4)
            debug["E3"] = round(e3, 4)
        else:
            e1 = e2 = e3 = None
            energy_has_recovery = False
            energy_is_declining = False

        inputs = {
            "pace_wpm": client_wpm,
            "pace_variance_wpm": None,
            "pause_avg_ms": avg_pause_ms,
            "speech_density": speech_density,
            "max_pause_s": max_pause_s,
            "has_dramatic_pause": has_dramatic_pause,
            "dynamic_range_db": dynamic_range_db,
            "rms_instability_db": rms_instability_db,
            "emphasis_spikes_per_min": emphasis_spikes_per_min,
            "emphasis_monotone": False,
            "emphasis_front_loaded": False,
            "e1": e1,
            "e2": e2,
            "e3": e3,
            "energy_has_recovery": energy_has_recovery,
            "energy_is_declining": energy_is_declining,
        }

        if include_debug:
            debug["window_duration_sec"] = round(window_time, 2)
            debug["voiced_duration_sec"] = round(voiced_dur_30, 2)
            debug["emphasis_event_count"] = emphasis_count
            debug["dynamic_p95"] = round(p95, 2)
            debug["dynamic_p5"] = round(p5, 2)
            if energy_result:
                debug["energy_slope"] = round((e3 - e1) / 3.0, 4) if (e1 and e3) else None

        return inputs, debug
    except Exception as e:
        return default_inputs, {"reason": "exception", "error": str(e)}


def clear_sniper_session(session_id: str) -> None:
    """Clear state for session (e.g. on abandon or end)."""
    _session_state.pop(session_id, None)
