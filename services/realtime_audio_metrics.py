"""
Real-time pause-only metrics for Ambient Glow.
Single live value: pause_score in [0, 1] (1 = ideal pausing). Brightness = function(pause_score).

- No pauses = bad. Too long / too many pauses = bad. Balanced pausing = good.
- VAD: 20 ms frames, frame silent if RMS dB < -45. Pause event = continuous silent run >= 200 ms.
- Stateful: 10 s rolling window per session; update 4–10×/sec via chunk requests.
- Output: seq, t_ms, voiced_ratio, pause_score. Silence gating: when not speaking, return neutral (pause_score=1).
"""
import math
from collections import deque
from typing import Deque, Dict, List, Tuple, Union

import numpy as np

TARGET_SAMPLE_RATE = 16000
FRAME_MS = 20
HOP_MS = 20  # no overlap: each frame is 20 ms, consecutive
RMS_FLOOR = 1e-8
SILENCE_DB_THRESHOLD = -45.0
VOICED_RATIO_GATE = 0.15
WINDOW_SEC = 10.0
MIN_PAUSE_EVENT_SEC = 0.2  # 200 ms
MIN_PAUSE_FRAMES = 10  # 200 ms at 20 ms/frame
MAX_PAUSE_GOOD_SEC = 2.5
MAX_PAUSE_HARD_SEC = 5.0

# Band scoring (middle good, extremes bad)
PAUSE_RATIO_CENTER = 0.20
PAUSE_RATIO_RADIUS = 0.15
PAUSES_PER_MIN_CENTER = 11.0
PAUSES_PER_MIN_RADIUS = 9.0

# Session state: next_t_sec = start time for next chunk's first frame; frames = (t_sec, is_silent)
_session_state: Dict[str, Dict] = {}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _smoothstep(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _band_score(x: float, center: float, radius: float) -> float:
    """Score in [0,1]; 1 at center, 0 at extremes."""
    if radius <= 0:
        return 1.0
    delta = _clamp((x - center) / radius, -1.0, 1.0)
    raw = 1.0 - abs(delta)
    return _smoothstep(raw)


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


def _compute_pause_events(frames: List[Tuple[float, bool]]) -> Tuple[float, float, int, float]:
    """
    From list of (t_sec, is_silent) compute:
    - silent_time (seconds)
    - window_time (seconds)
    - num_pause_events (runs of silent >= 200 ms)
    - max_pause_s (longest run in seconds)
    """
    if not frames:
        return 0.0, 0.0, 0, 0.0
    frame_dur = FRAME_MS / 1000.0
    t_min = frames[0][0]
    t_max = frames[-1][0] + frame_dur
    window_time = t_max - t_min
    if window_time <= 0:
        window_time = frame_dur * len(frames)

    silent_time = 0.0
    num_events = 0
    max_pause_s = 0.0
    run_start = None

    for t_sec, is_silent in frames:
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
                run_start = None
    if run_start is not None:
        run_dur = (frames[-1][0] + frame_dur) - run_start
        if run_dur >= MIN_PAUSE_EVENT_SEC:
            num_events += 1
            max_pause_s = max(max_pause_s, run_dur)

    return silent_time, window_time, num_events, max_pause_s


def _pause_just_ended(
    frames: List[Tuple[float, bool]], return_debug: bool = False
) -> Union[bool, Tuple[bool, dict]]:
    """
    True if a pause event (>= 200 ms silence) just ended in this chunk.
    If return_debug=True, returns (result, debug_dict) for logging.
    """
    debug: dict = {}
    if len(frames) < MIN_PAUSE_FRAMES + 2:
        if return_debug:
            debug["pause_why"] = "too_few_frames"
            debug["frames_count"] = len(frames)
            return False, debug
        return False
    if frames[-1][1]:
        if return_debug:
            debug["pause_why"] = "last_frame_silent"
            debug["tail_20"] = _tail_frames_str(frames, 20)
            return False, debug
        return False
    # Find start of trailing voiced run
    i = len(frames) - 1
    while i >= 0 and not frames[i][1]:
        i -= 1
    first_voiced_after_pause = i + 1
    if first_voiced_after_pause >= len(frames):
        if return_debug:
            debug["pause_why"] = "no_voiced_after"
            return False, debug
        return False
    run_silent = 0
    j = i
    while j >= 0 and frames[j][1]:
        run_silent += 1
        j -= 1
    had_voice_before = j >= 0
    if return_debug:
        debug["run_silent_frames"] = run_silent
        debug["run_silent_ms"] = run_silent * FRAME_MS
        debug["had_voice_before_pause"] = had_voice_before
        debug["min_required_frames"] = MIN_PAUSE_FRAMES
        debug["tail_20"] = _tail_frames_str(frames, 20)
        debug["window_frames"] = len(frames)
    if run_silent < MIN_PAUSE_FRAMES:
        if return_debug:
            debug["pause_why"] = "run_too_short"
            return False, debug
        return False
    if not had_voice_before:
        if return_debug:
            debug["pause_why"] = "initial_silence"
            return False, debug
        return False
    if return_debug:
        debug["pause_why"] = "ok"
        return True, debug
    return True


def _tail_frames_str(frames: List[Tuple[float, bool]], n: int) -> str:
    """Last n frames as 'V' (voiced) / 'S' (silent), newest last."""
    tail = frames[-n:] if len(frames) >= n else frames
    return "".join("S" if f[1] else "V" for f in tail)


def _pause_score_from_metrics(
    pause_ratio: float,
    pauses_per_min: float,
    max_pause_s: float,
) -> float:
    """Single pause_score: worst of ratio band, freq band, and long-pause penalty."""
    ratio_score = _band_score(pause_ratio, PAUSE_RATIO_CENTER, PAUSE_RATIO_RADIUS)
    freq_score = _band_score(
        pauses_per_min, PAUSES_PER_MIN_CENTER, PAUSES_PER_MIN_RADIUS
    )
    # long_score: 1 if max_pause_s <= 2.5, 0 if >= 5, linear in between
    long_score = 1.0 - _clamp(
        (max_pause_s - MAX_PAUSE_GOOD_SEC) / (MAX_PAUSE_HARD_SEC - MAX_PAUSE_GOOD_SEC),
        0.0,
        1.0,
    )
    combined = min(ratio_score, freq_score) * long_score
    return _smoothstep(combined)


def process_pcm_chunk(
    pcm_bytes: bytes,
    sample_rate: int,
    session_id: str,
    seq: int = 0,
    t_ms: int = 0,
    include_debug: bool = False,
) -> dict:
    """
    Process one chunk; update 10 s rolling window for this session; return pause_score.
    Returns: seq, t_ms, voiced_ratio, pause_score.
    When voiced_ratio < VOICED_RATIO_GATE, returns neutral (pause_score=1).
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

        dbs = _frame_rms_db(sig, frame_size, hop)
        is_silent = dbs < SILENCE_DB_THRESHOLD
        n_frames = len(is_silent)
        voiced_ratio = float(np.mean(~is_silent)) if n_frames else 0.0
        voiced_ratio = max(0.0, min(1.0, voiced_ratio))

        # Silence gating: don't punish when user is not speaking
        if voiced_ratio < VOICED_RATIO_GATE:
            return _neutral_response(seq, t_ms, voiced_ratio, include_debug)

        chunk_dur_sec = len(sig) / float(sample_rate)

        # Get or create session state
        if session_id not in _session_state:
            _session_state[session_id] = {
                "next_t_sec": 0.0,
                "frames": deque(maxlen=5000),  # 10s at 20ms = 500; extra headroom
            }
        state = _session_state[session_id]
        next_t = state["next_t_sec"]
        frames_deque: Deque[Tuple[float, bool]] = state["frames"]
        frame_dur = FRAME_MS / 1000.0

        # Append this chunk's frames
        for i in range(n_frames):
            t_sec = next_t + i * frame_dur
            frames_deque.append((t_sec, bool(is_silent[i])))
        next_t += chunk_dur_sec
        state["next_t_sec"] = next_t

        # Evict older than 10 s
        while frames_deque and frames_deque[0][0] < next_t - WINDOW_SEC:
            frames_deque.popleft()

        frames_list = list(frames_deque)
        silent_time, window_time, num_events, max_pause_s = _compute_pause_events(
            frames_list
        )
        if window_time <= 0:
            pause_ratio = 0.0
            pauses_per_min = 0.0
        else:
            pause_ratio = silent_time / window_time
            pauses_per_min = (num_events / window_time) * 60.0

        pause_score = _pause_score_from_metrics(
            pause_ratio, pauses_per_min, max_pause_s
        )
        if include_debug:
            pause_detected, pause_debug = _pause_just_ended(frames_list, return_debug=True)
        else:
            pause_detected = _pause_just_ended(frames_list)

        # pitch_variance: fixed real-time metric (stub: 0–1; real F0 variance can be computed later)
        pitch_variance = round(0.5, 2) if voiced_ratio < VOICED_RATIO_GATE else round(_clamp(0.3 + voiced_ratio * 0.5, 0, 1), 2)
        out = {
            "seq": seq,
            "t_ms": t_ms,
            "voiced_ratio": round(voiced_ratio, 2),
            "pause_score": round(float(pause_score), 2),
            "pause_detected": pause_detected,
            "pitch_variance": pitch_variance,
        }
        if include_debug:
            out["_debug"] = {
                "pause_ratio": round(pause_ratio, 2),
                "pauses_per_min": round(pauses_per_min, 1),
                "max_pause_s": round(max_pause_s, 2),
                "window_time": round(window_time, 2),
                "pause_detected": pause_detected,
                "pause_detection": pause_debug,
            }
        return out
    except Exception:
        return _neutral_response(seq, t_ms, 0.0, include_debug)


def _neutral_response(
    seq: int, t_ms: int, voiced_ratio: float, include_debug: bool
) -> dict:
    """When chunk empty or silence-gated: neutral glow (pause_score=1)."""
    out = {
        "seq": seq,
        "t_ms": t_ms,
        "voiced_ratio": round(max(0.0, min(1.0, voiced_ratio)), 2),
        "pause_score": 1.0,
        "pause_detected": False,
        "pitch_variance": 0.5,
    }
    if include_debug:
        out["_debug"] = {
            "pause_ratio": None,
            "pauses_per_min": None,
            "max_pause_s": None,
            "window_time": None,
            "pause_detected": False,
            "pause_detection": {"pause_why": "silence_gated", "voiced_ratio_below": VOICED_RATIO_GATE},
        }
    return out


def clear_session_state(session_id: str) -> None:
    """Remove stored window for a session (e.g. when recording ends). Optional cleanup."""
    _session_state.pop(session_id, None)
