"""
Live Coach — simple flow scoring.
pace_score: not used live (no real-time WPM yet); will plug in via X-WPM header later.
flow_score: from pause_ratio (0–100).
performance_score: flow_score (or 0.6*pace + 0.4*flow when pace is available).
"""

from typing import Optional


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def score_flow(pause_ratio: Optional[float]) -> Optional[float]:
    """
    Flow score 0–100 from pause_ratio.
    Good band (0.15–0.30) → 100.
    Too rushed (< 0.15): linear ramp.
    Too choppy (> 0.30): linear ramp down to 0 at 0.60.
    """
    if pause_ratio is None:
        return None
    if 0.15 <= pause_ratio <= 0.30:
        return 100.0
    if pause_ratio < 0.15:
        return _clamp((pause_ratio / 0.15) * 100.0, 0.0, 100.0)
    return _clamp(((0.60 - pause_ratio) / (0.60 - 0.30)) * 100.0, 0.0, 100.0)


def score_pace(wpm: Optional[float]) -> Optional[float]:
    """
    Pace score 0–100 from WPM.
    Good band (125–165) → 100.
    Below 125: linear ramp from 0 at 80 WPM.
    Above 165: linear ramp down to 0 at 210 WPM.
    Not used live yet (no real-time WPM). Included for post-upload report.
    """
    if wpm is None:
        return None
    if 125 <= wpm <= 165:
        return 100.0
    if wpm < 125:
        return _clamp((wpm - 80) / (125 - 80) * 100.0, 0.0, 100.0)
    return _clamp((210 - wpm) / (210 - 165) * 100.0, 0.0, 100.0)


def combine_scores(
    pace_score: Optional[float],
    flow_score: Optional[float],
) -> Optional[float]:
    """Weighted combination: 60% pace + 40% flow. Falls back to whichever is available."""
    if pace_score is not None and flow_score is not None:
        return round(0.6 * pace_score + 0.4 * flow_score, 1)
    if pace_score is not None:
        return round(pace_score, 1)
    if flow_score is not None:
        return round(flow_score, 1)
    return None


def compute_flow_offset(pause_ratio: Optional[float]) -> float:
    """
    Y-axis offset –1 to +1 for the sniper ball.
    +1 = too rushed (few pauses), 0 = balanced, –1 = too many pauses.
    """
    if pause_ratio is None:
        return 0.0
    ideal = 0.225
    max_dev = 0.18
    return _clamp((ideal - pause_ratio) / max_dev, -1.0, 1.0)


def coach_color(score: Optional[float]) -> str:
    if score is None:
        return "gray"
    if score >= 75:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def compute_simple_live(
    pause_ratio: Optional[float],
    client_wpm: Optional[float] = None,
    voiced_ratio: float = 0.0,
    silence_gated: bool = False,
) -> dict:
    """
    Build the simple_live response dict for the sniper-metrics-chunk endpoint.
    """
    if silence_gated:
        return {
            "pause_ratio": pause_ratio or 0.0,
            "flow_score": None,
            "performance_score": None,
            "flow_offset": 0.0,
            "pace_offset": 0.0,
            "coach_color": "gray",
            "voiced_ratio": voiced_ratio,
            "silence_gated": True,
        }

    flow = score_flow(pause_ratio)
    pace = score_pace(client_wpm)
    perf = combine_scores(pace, flow)
    f_offset = compute_flow_offset(pause_ratio)
    p_offset = 0.0  # always 0 until frontend sends live WPM

    return {
        "pause_ratio": round(pause_ratio or 0.0, 4),
        "flow_score": round(flow, 1) if flow is not None else None,
        "performance_score": round(perf, 1) if perf is not None else None,
        "flow_offset": round(f_offset, 4),
        "pace_offset": p_offset,
        "coach_color": coach_color(perf),
        "voiced_ratio": round(voiced_ratio, 4),
        "silence_gated": False,
    }
