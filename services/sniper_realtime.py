"""
Live Coach — real-time pause detection from PCM.
Rolling 30s window. Returns pause_ratio for sniper_scoring.compute_simple_live().
"""
import math
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

TARGET_SAMPLE_RATE = 16000
FRAME_MS = 20
HOP_MS = 20
RMS_FLOOR = 1e-8
SILENCE_DB_THRESHOLD = -45.0
VOICED_RATIO_GATE = 0.08
WINDOW_30_SEC = 30.0
MIN_PAUSE_EVENT_SEC = 0.2

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


def _compute_pause_ratio(
    frames: List[Tuple[float, bool, float]],
) -> Tuple[float, float]:
    """Returns (silent_time, window_time)."""
    if not frames:
        return 0.0, 0.0
    frame_dur = FRAME_MS / 1000.0
    t_min = frames[0][0]
    t_max = frames[-1][0] + frame_dur
    window_time = t_max - t_min
    if window_time <= 0:
        window_time = frame_dur * len(frames)
    silent_time = sum(frame_dur for _, is_silent, _ in frames if is_silent)
    return silent_time, window_time


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
    Process one PCM chunk; update 30s buffer; return (sniper_inputs, debug).
    sniper_inputs keys: pause_ratio, voiced_ratio, silence_gated, client_wpm.
    Pass to sniper_scoring.compute_simple_live().
    """
    debug: Dict[str, Any] = {}
    default_inputs = {
        "pause_ratio": None,
        "voiced_ratio": 0.0,
        "silence_gated": True,
        "client_wpm": client_wpm,
    }

    if len(pcm_bytes) < 2:
        return default_inputs, {"reason": "empty_chunk"}

    try:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if samples.size == 0:
            return default_inputs, {"reason": "empty_buffer"}
        sig = samples.astype(np.float32) / 32768.0

        if sample_rate != TARGET_SAMPLE_RATE:
            sig = _resample_to_16k(sig, sample_rate)
            sample_rate = TARGET_SAMPLE_RATE

        frame_size = int(FRAME_MS * sample_rate / 1000)
        hop = int(HOP_MS * sample_rate / 1000)
        if frame_size < 2 or hop < 1:
            return default_inputs, {"reason": "invalid_frame"}

        dbs = _frame_rms_db(sig, frame_size, hop)
        is_silent = dbs < SILENCE_DB_THRESHOLD
        n_frames = len(is_silent)
        voiced_ratio = float(np.mean(~is_silent)) if n_frames else 0.0
        voiced_ratio = max(0.0, min(1.0, voiced_ratio))

        if voiced_ratio < VOICED_RATIO_GATE:
            return {
                "pause_ratio": None,
                "voiced_ratio": voiced_ratio,
                "silence_gated": True,
                "client_wpm": client_wpm,
            }, {"reason": "silence_gated", "voiced_ratio": voiced_ratio}

        chunk_dur_sec = len(sig) / float(sample_rate)
        frame_dur = FRAME_MS / 1000.0

        if session_id not in _session_state:
            _session_state[session_id] = {
                "next_t_sec": 0.0,
                "frames_30s": deque(maxlen=2000),
            }
        state = _session_state[session_id]
        next_t = state["next_t_sec"]

        for i in range(n_frames):
            t_sec = next_t + i * frame_dur
            state["frames_30s"].append((t_sec, bool(is_silent[i]), float(dbs[i])))

        next_t += chunk_dur_sec
        state["next_t_sec"] = next_t

        # Keep only last 30s
        while state["frames_30s"] and state["frames_30s"][0][0] < next_t - WINDOW_30_SEC:
            state["frames_30s"].popleft()

        frames_30 = list(state["frames_30s"])
        if not frames_30:
            return default_inputs, {"reason": "no_frames_30"}

        silent_time, window_time = _compute_pause_ratio(frames_30)
        pause_ratio = silent_time / window_time if window_time > 0 else 0.0
        pause_ratio = max(0.0, min(1.0, pause_ratio))

        if include_debug:
            debug["window_duration_sec"] = round(window_time, 2)
            debug["voiced_ratio"] = round(voiced_ratio, 4)
            debug["pause_ratio"] = round(pause_ratio, 4)

        return {
            "pause_ratio": pause_ratio,
            "voiced_ratio": voiced_ratio,
            "silence_gated": False,
            "client_wpm": client_wpm,
        }, debug

    except Exception as e:
        return default_inputs, {"reason": "exception", "error": str(e)}


def clear_sniper_session(session_id: str) -> None:
    """Clear state for session (e.g. on abandon or end)."""
    _session_state.pop(session_id, None)
