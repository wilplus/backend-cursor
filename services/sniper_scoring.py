"""
Sniper Wheel — Public Speaking Mode v1.
Elite performance coach scoring: 5 segments (Pace, Pause, Dynamic, Emphasis, Energy Arc).
Gaussian proximity curves; reweight when pace unavailable; deterministic coaching priority.
Backend Refinement Addendum: level-invariant energy, pace_available, score_completeness.
"""
import math
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Zone bounds (for API: green / yellow / red)
# ---------------------------------------------------------------------------

# 1. PACE CONTROL — WPM
PACE_IDEAL_WPM = 147
PACE_GREEN_LOW = 140
PACE_GREEN_HIGH = 155
PACE_YELLOW_LOW = 130
PACE_YELLOW_HIGH = 165
PACE_TOLERANCE = 8
PACE_VARIANCE_MIN_WPM = 40
PACE_HARD_CAP_SCORE = 40

# 2. PAUSE DISCIPLINE — ms
PAUSE_IDEAL_MS = 440
PAUSE_GREEN_LOW_MS = 400
PAUSE_GREEN_HIGH_MS = 480
PAUSE_YELLOW_LOW_MS = 320
PAUSE_YELLOW_HIGH_MS = 600
PAUSE_TOLERANCE_MS = 70
SPEECH_DENSITY_MAX_PENALTY = 0.82
NO_DRAMATIC_PAUSE_PENALTY = 15
DRAMATIC_PAUSE_MIN_SEC = 1.5

# 3. DYNAMIC STRENGTH — dB (percentile-based: p95 - p5)
DYNAMIC_IDEAL_DB = 14.0
DYNAMIC_GREEN_LOW_DB = 12.0
DYNAMIC_GREEN_HIGH_DB = 16.0
DYNAMIC_YELLOW_LOW_DB = 9.0
DYNAMIC_YELLOW_HIGH_DB = 18.0
DYNAMIC_TOLERANCE_DB = 2.0
DYNAMIC_HARD_CAP_SCORE = 35
RMS_INSTABILITY_THRESHOLD_DB = 5.0

# 4. EMPHASIS PRECISION — true spikes/min
EMPHASIS_IDEAL_PER_MIN = 35
EMPHASIS_GREEN_LOW = 25
EMPHASIS_GREEN_HIGH = 45
EMPHASIS_YELLOW_LOW = 15
EMPHASIS_YELLOW_HIGH = 60
EMPHASIS_TOLERANCE = 8
EMPHASIS_CAP_SCORE_BELOW = 40
EMPHASIS_MONOTONE_PENALTY = 5

# 5. ENERGY ARC (level-invariant: normalized E1/E2/E3)
ENERGY_RECOVERY_BONUS = 20
ENERGY_DECLINE_PENALTY = 25
ENERGY_DECLINE_THRESHOLD = 0.15
ENERGY_BASE_SCORE = 70

# Original weights (when pace available)
WEIGHT_PACE = 0.18
WEIGHT_PAUSE = 0.18
WEIGHT_DYNAMIC = 0.18
WEIGHT_EMPHASIS = 0.16
WEIGHT_ENERGY = 0.30

# Reweighted when pace unavailable: new = original / (1 - 0.18)
WEIGHT_PAUSE_NO_PACE = 0.18 / 0.82   # ~0.2195 → use 22%
WEIGHT_DYNAMIC_NO_PACE = 0.18 / 0.82
WEIGHT_EMPHASIS_NO_PACE = 0.16 / 0.82
WEIGHT_ENERGY_NO_PACE = 0.30 / 0.82

# Tiers
TIER_EXECUTIVE = (92, 100)
TIER_STAGE_READY = (85, 91)
TIER_STRUCTURED = (75, 84)
TIER_DEVELOPING = (60, 74)

# Coaching priority order (structural first)
COACHING_PRIORITY = ["energy", "pause", "pace", "emphasis", "dynamic"]

# Soft floor: score = floor + (100 - floor) * (raw/100). Energy has no floor (structural honesty).
PACE_SOFT_FLOOR = 55
PAUSE_SOFT_FLOOR = 55
DYNAMIC_SOFT_FLOOR = 60
EMPHASIS_SOFT_FLOOR = 60

# Catastrophic zone: bypass soft floor so score can drop to 30–40 (preserve credibility).
PACE_CATASTROPHIC_LOW_WPM = 110
PACE_CATASTROPHIC_HIGH_WPM = 190
DYNAMIC_CATASTROPHIC_LOW_DB = 6.0
EMPHASIS_CATASTROPHIC_LOW_PER_MIN = 8.0

# Adaptive: baseline ready after N sessions with at least one having energy.
BASELINE_READY_SESSION_COUNT = 3
ENERGY_IDEAL_RATIO = 1.0  # E3/E2 >= 1
IMPROVEMENT_EPSILON = 1e-6
BLEND_STAGE_WEIGHT = 0.70
BLEND_GROWTH_WEIGHT = 0.30


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _gaussian_score(deviation: float, tolerance: float) -> float:
    if tolerance <= 0:
        return 100.0
    return 100.0 * math.exp(-(deviation * deviation) / (2.0 * tolerance * tolerance))


def _apply_soft_floor(raw_score: float, floor: float, in_catastrophic_zone: bool) -> float:
    """Apply soft floor unless in catastrophic zone (then allow low score for credibility)."""
    if in_catastrophic_zone:
        return raw_score
    if floor <= 0:
        return raw_score
    gaussian_norm = raw_score / 100.0
    return floor + (100.0 - floor) * gaussian_norm


def zone_for_value(
    value: float,
    green_low: float,
    green_high: float,
    yellow_low: float,
    yellow_high: float,
) -> str:
    if green_low <= value <= green_high:
        return "green"
    if yellow_low <= value <= yellow_high:
        return "yellow"
    return "red"


def score_pace(
    wpm: Optional[float],
    segment_variance_wpm: Optional[float] = None,
) -> Tuple[Optional[float], str, Optional[float], Optional[float]]:
    """Returns (score_0_100 or None if unavailable, zone, raw_wpm, variance)."""
    if wpm is None:
        return (None, "unavailable", None, segment_variance_wpm)
    wpm = float(wpm)
    if wpm < PACE_YELLOW_LOW or wpm > PACE_YELLOW_HIGH:
        capped = min(
            PACE_HARD_CAP_SCORE,
            _gaussian_score(abs(wpm - PACE_IDEAL_WPM), PACE_TOLERANCE),
        )
        zone = zone_for_value(
            wpm, PACE_GREEN_LOW, PACE_GREEN_HIGH, PACE_YELLOW_LOW, PACE_YELLOW_HIGH
        )
        score = capped
    else:
        deviation = abs(wpm - PACE_IDEAL_WPM)
        score = _gaussian_score(deviation, PACE_TOLERANCE)
        if segment_variance_wpm is not None and segment_variance_wpm >= PACE_VARIANCE_MIN_WPM:
            score = min(100.0, score + 5.0)
        zone = zone_for_value(
            wpm, PACE_GREEN_LOW, PACE_GREEN_HIGH, PACE_YELLOW_LOW, PACE_YELLOW_HIGH
        )
    catastrophic = wpm < PACE_CATASTROPHIC_LOW_WPM or wpm > PACE_CATASTROPHIC_HIGH_WPM
    score = _apply_soft_floor(score, PACE_SOFT_FLOOR, catastrophic)
    score = _clamp(score, 0, 100)
    return (round(score, 1), zone, wpm, segment_variance_wpm)


def score_pause(
    avg_pause_ms: float,
    speech_density: float,
    max_pause_s: float,
    has_dramatic_pause_in_window: bool,
) -> Tuple[float, str]:
    deviation = abs(avg_pause_ms - PAUSE_IDEAL_MS)
    score = _gaussian_score(deviation, PAUSE_TOLERANCE_MS)
    if speech_density > SPEECH_DENSITY_MAX_PENALTY:
        score = max(0, score - 10)
    if not has_dramatic_pause_in_window:
        score = max(0, score - NO_DRAMATIC_PAUSE_PENALTY)
    score = _clamp(score, 0, 100)
    score = _apply_soft_floor(score, PAUSE_SOFT_FLOOR, False)
    score = _clamp(score, 0, 100)
    zone = zone_for_value(
        avg_pause_ms,
        PAUSE_GREEN_LOW_MS,
        PAUSE_GREEN_HIGH_MS,
        PAUSE_YELLOW_LOW_MS,
        PAUSE_YELLOW_HIGH_MS,
    )
    return (round(score, 1), zone)


def score_dynamic(
    dynamic_range_db: float,
    rms_instability_db: Optional[float] = None,
) -> Tuple[float, str]:
    if dynamic_range_db < DYNAMIC_YELLOW_LOW_DB or dynamic_range_db > DYNAMIC_YELLOW_HIGH_DB:
        score = min(
            DYNAMIC_HARD_CAP_SCORE,
            _gaussian_score(
                abs(dynamic_range_db - DYNAMIC_IDEAL_DB), DYNAMIC_TOLERANCE_DB
            ),
        )
    else:
        deviation = abs(dynamic_range_db - DYNAMIC_IDEAL_DB)
        score = _gaussian_score(deviation, DYNAMIC_TOLERANCE_DB)
    if rms_instability_db is not None and rms_instability_db > RMS_INSTABILITY_THRESHOLD_DB:
        score = max(0, score - 10)
    score = _clamp(score, 0, 100)
    catastrophic = dynamic_range_db < DYNAMIC_CATASTROPHIC_LOW_DB
    score = _apply_soft_floor(score, DYNAMIC_SOFT_FLOOR, catastrophic)
    score = _clamp(score, 0, 100)
    zone = zone_for_value(
        dynamic_range_db,
        DYNAMIC_GREEN_LOW_DB,
        DYNAMIC_GREEN_HIGH_DB,
        DYNAMIC_YELLOW_LOW_DB,
        DYNAMIC_YELLOW_HIGH_DB,
    )
    return (round(score, 1), zone)


def score_emphasis(
    spikes_per_min: float,
    is_monotone: bool = False,
    is_front_loaded: bool = False,
) -> Tuple[float, str]:
    if spikes_per_min < EMPHASIS_YELLOW_LOW:
        score = min(
            EMPHASIS_CAP_SCORE_BELOW,
            _gaussian_score(
                abs(spikes_per_min - EMPHASIS_IDEAL_PER_MIN), EMPHASIS_TOLERANCE
            ),
        )
    else:
        deviation = abs(spikes_per_min - EMPHASIS_IDEAL_PER_MIN)
        score = _gaussian_score(deviation, EMPHASIS_TOLERANCE)
    if is_monotone:
        score = max(0, score - EMPHASIS_MONOTONE_PENALTY)
    if is_front_loaded:
        score = max(0, score - 5)
    score = _clamp(score, 0, 100)
    catastrophic = spikes_per_min < EMPHASIS_CATASTROPHIC_LOW_PER_MIN
    score = _apply_soft_floor(score, EMPHASIS_SOFT_FLOOR, catastrophic)
    score = _clamp(score, 0, 100)
    zone = zone_for_value(
        spikes_per_min,
        EMPHASIS_GREEN_LOW,
        EMPHASIS_GREEN_HIGH,
        EMPHASIS_YELLOW_LOW,
        EMPHASIS_YELLOW_HIGH,
    )
    return (round(score, 1), zone)


def score_energy_arc(
    e1: float,
    e2: float,
    e3: float,
    has_recovery: bool = False,
    is_declining: bool = False,
) -> Tuple[float, str]:
    """E1/E2/E3 are normalized (e.g. ThirdMeanRMS / SessionMeanRMS). Score only relative structure."""
    score = ENERGY_BASE_SCORE
    if e3 >= e2:
        score += ENERGY_RECOVERY_BONUS
    elif e2 > 0 and (e2 - e3) / e2 > ENERGY_DECLINE_THRESHOLD:
        score -= ENERGY_DECLINE_PENALTY
    if has_recovery:
        score = min(100, score + 5)
    if is_declining:
        score = max(0, score - 10)
    score = _clamp(score, 0, 100)
    if e3 >= e2 and not is_declining:
        pattern = "Stable Build"
    elif is_declining:
        pattern = "Energy Declining"
    elif has_recovery:
        pattern = "Recovery"
    else:
        pattern = "Flat"
    return (round(score, 1), pattern)


def tier_label(overall_score: float) -> str:
    if TIER_EXECUTIVE[0] <= overall_score <= TIER_EXECUTIVE[1]:
        return "Executive Calibrated"
    if TIER_STAGE_READY[0] <= overall_score <= TIER_STAGE_READY[1]:
        return "Stage Ready"
    if TIER_STRUCTURED[0] <= overall_score <= TIER_STRUCTURED[1]:
        return "Structured"
    if TIER_DEVELOPING[0] <= overall_score <= TIER_DEVELOPING[1]:
        return "Developing Control"
    return "Unstable Delivery"


def _coaching_message_for_segment(
    segment: str,
    pace_wpm: Optional[float],
    pace_zone: str,
    pause_avg_ms: float,
    pause_zone: str,
    dynamic_db: float,
    dynamic_zone: str,
    emphasis_per_min: float,
    emphasis_zone: str,
    energy_pattern: str,
) -> Optional[str]:
    """Return one actionable message for this segment if zone != green and actionable."""
    if segment == "pace" and pace_zone != "green" and pace_zone != "unavailable" and pace_wpm is not None:
        delta = pace_wpm - PACE_IDEAL_WPM
        if delta > 5:
            return f"Slow by {abs(int(delta))} WPM for stronger authority."
        if delta < -5:
            return f"Add about {abs(int(delta))} WPM so ideas land clearly."
    if segment == "pause" and pause_zone != "green":
        if pause_avg_ms < PAUSE_GREEN_LOW_MS:
            return "Extend sentence-end pauses by ~200 ms."
        if pause_avg_ms > PAUSE_GREEN_HIGH_MS:
            return "Tighten pauses slightly; keep rhythm."
    if segment == "dynamic" and dynamic_zone != "green":
        if dynamic_db < DYNAMIC_GREEN_LOW_DB:
            return "Increase vocal contrast for impact."
        if dynamic_db > DYNAMIC_GREEN_HIGH_DB:
            return "Smooth dynamics for consistency."
    if segment == "emphasis" and emphasis_zone != "green":
        if emphasis_per_min < EMPHASIS_GREEN_LOW:
            return "Add emphasis on key phrases."
        if emphasis_per_min > EMPHASIS_GREEN_HIGH:
            return "Reduce emphasis frequency for clarity."
    if segment == "energy" and ("Declining" in energy_pattern or energy_pattern == "Flat"):
        return "Rebuild intensity through vocal lift."
    return None


def select_coaching_message(
    pace_wpm: Optional[float],
    pace_zone: str,
    pause_avg_ms: float,
    pause_zone: str,
    dynamic_db: float,
    dynamic_zone: str,
    emphasis_per_min: float,
    emphasis_zone: str,
    energy_pattern: str,
) -> str:
    """Deterministic priority: Energy → Pause → Pace → Emphasis → Dynamic. One message only."""
    for segment in COACHING_PRIORITY:
        msg = _coaching_message_for_segment(
            segment,
            pace_wpm, pace_zone,
            pause_avg_ms, pause_zone,
            dynamic_db, dynamic_zone,
            emphasis_per_min, emphasis_zone,
            energy_pattern,
        )
        if msg:
            return msg
    return "Delivery controlled. Maintain rhythm."


def _improvement_ratio(baseline_dist: float, current_dist: float) -> float:
    """Improvement = 1 - (current_distance / max(baseline_distance, epsilon)); clamp [0, 1]."""
    denom = max(baseline_dist, IMPROVEMENT_EPSILON)
    return _clamp(1.0 - (current_dist / denom), 0.0, 1.0)


def compute_growth_score(
    baseline: Dict[str, Any],
    current_wpm: Optional[float],
    current_pause_ms: float,
    current_dynamic_db: float,
    current_emphasis_per_min: float,
    current_energy_ratio: Optional[float],
    pace_available: bool,
    energy_available: bool,
) -> Tuple[Optional[float], Dict[str, float]]:
    """
    Growth score 0–100 from improvement vs baseline. Same weights as stage.
    Energy improvement: 1 - |current_ratio - 1| / max(|baseline_ratio - 1|, epsilon).
    Returns (growth_score or None if baseline missing required fields, improvements_dict).
    """
    improvements: Dict[str, float] = {}
    base_wpm = baseline.get("baseline_wpm")
    base_pause = baseline.get("baseline_pause_ms")
    base_dynamic = baseline.get("baseline_dynamic_db")
    base_emphasis = baseline.get("baseline_emphasis_per_min")
    base_energy_ratio = baseline.get("baseline_energy_ratio")

    if pace_available and current_wpm is not None and base_wpm is not None:
        bd = abs(float(base_wpm) - PACE_IDEAL_WPM)
        cd = abs(float(current_wpm) - PACE_IDEAL_WPM)
        improvements["pace"] = _improvement_ratio(bd, cd)
    if base_pause is not None:
        bd = abs(float(base_pause) - PAUSE_IDEAL_MS)
        cd = abs(current_pause_ms - PAUSE_IDEAL_MS)
        improvements["pause"] = _improvement_ratio(bd, cd)
    if base_dynamic is not None:
        bd = abs(float(base_dynamic) - DYNAMIC_IDEAL_DB)
        cd = abs(current_dynamic_db - DYNAMIC_IDEAL_DB)
        improvements["dynamic"] = _improvement_ratio(bd, cd)
    if base_emphasis is not None:
        bd = abs(float(base_emphasis) - EMPHASIS_IDEAL_PER_MIN)
        cd = abs(current_emphasis_per_min - EMPHASIS_IDEAL_PER_MIN)
        improvements["emphasis"] = _improvement_ratio(bd, cd)
    if energy_available and base_energy_ratio is not None and current_energy_ratio is not None:
        br = float(base_energy_ratio)
        cr = float(current_energy_ratio)
        base_dist = abs(br - ENERGY_IDEAL_RATIO)
        current_dist = abs(cr - ENERGY_IDEAL_RATIO)
        improvements["energy"] = _improvement_ratio(base_dist, current_dist)

    if not improvements:
        return None, improvements

    if pace_available and "pace" in improvements:
        if energy_available and "energy" in improvements:
            total = (
                improvements.get("pace", 0) * WEIGHT_PACE
                + improvements.get("pause", 0) * WEIGHT_PAUSE
                + improvements.get("dynamic", 0) * WEIGHT_DYNAMIC
                + improvements.get("emphasis", 0) * WEIGHT_EMPHASIS
                + improvements.get("energy", 0) * WEIGHT_ENERGY
            )
        else:
            total = (
                improvements.get("pace", 0) * WEIGHT_PACE
                + improvements.get("pause", 0) * WEIGHT_PAUSE
                + improvements.get("dynamic", 0) * WEIGHT_DYNAMIC
                + improvements.get("emphasis", 0) * WEIGHT_EMPHASIS
            )
            total = total / (1.0 - WEIGHT_ENERGY)
    else:
        total = (
            improvements.get("pause", 0) * WEIGHT_PAUSE_NO_PACE
            + improvements.get("dynamic", 0) * WEIGHT_DYNAMIC_NO_PACE
            + improvements.get("emphasis", 0) * WEIGHT_EMPHASIS_NO_PACE
            + improvements.get("energy", 0) * WEIGHT_ENERGY_NO_PACE
        )
        if energy_available and "energy" not in improvements:
            total = total / (1.0 - WEIGHT_ENERGY)

    growth_score = round(_clamp(total * 100.0, 0, 100), 1)
    return growth_score, improvements


def compute_sniper_state(
    pace_wpm: Optional[float] = None,
    pace_variance_wpm: Optional[float] = None,
    pause_avg_ms: float = 440.0,
    speech_density: float = 0.75,
    max_pause_s: float = 0.0,
    has_dramatic_pause: bool = False,
    dynamic_range_db: float = 14.0,
    rms_instability_db: Optional[float] = None,
    emphasis_spikes_per_min: float = 35.0,
    emphasis_monotone: bool = False,
    emphasis_front_loaded: bool = False,
    e1: Optional[float] = None,
    e2: Optional[float] = None,
    e3: Optional[float] = None,
    energy_has_recovery: bool = False,
    energy_is_declining: bool = False,
    baseline: Optional[Dict[str, Any]] = None,
    session_count: int = 0,
) -> Dict[str, Any]:
    """
    Full sniper state for one tick. Reweights when pace unavailable.
    If baseline and session_count >= BASELINE_READY_SESSION_COUNT and profile has energy, computes growth and blend.
    Returns segments, overall_score (stage), display_score (blend or stage), growth_score, baseline_ready, session_count,
    tier, coaching_message, pace_available, score_completeness, live.
    """
    pace_score, pace_zone, raw_wpm, _ = score_pace(pace_wpm, pace_variance_wpm)
    pause_score, pause_zone = score_pause(
        pause_avg_ms, speech_density, max_pause_s, has_dramatic_pause
    )
    dynamic_score, dynamic_zone = score_dynamic(dynamic_range_db, rms_instability_db)
    emphasis_score, emphasis_zone = score_emphasis(
        emphasis_spikes_per_min, emphasis_monotone, emphasis_front_loaded
    )

    if e1 is not None and e2 is not None and e3 is not None:
        energy_score, energy_pattern = score_energy_arc(
            e1, e2, e3, energy_has_recovery, energy_is_declining
        )
    else:
        energy_score = ENERGY_BASE_SCORE
        energy_pattern = "—"

    pace_available = pace_wpm is not None
    energy_available = e1 is not None and e2 is not None and e3 is not None

    if pace_available:
        total = (
            pace_score * WEIGHT_PACE
            + pause_score * WEIGHT_PAUSE
            + dynamic_score * WEIGHT_DYNAMIC
            + emphasis_score * WEIGHT_EMPHASIS
            + energy_score * WEIGHT_ENERGY
        )
        score_completeness = "full"
    else:
        total = (
            pause_score * WEIGHT_PAUSE_NO_PACE
            + dynamic_score * WEIGHT_DYNAMIC_NO_PACE
            + emphasis_score * WEIGHT_EMPHASIS_NO_PACE
            + energy_score * WEIGHT_ENERGY_NO_PACE
        )
        score_completeness = "partial"

    if not energy_available:
        score_completeness = "partial"

    overall_score = round(total, 0)
    overall_score = int(_clamp(overall_score, 0, 100))

    baseline_ready = (
        baseline is not None
        and session_count >= BASELINE_READY_SESSION_COUNT
        and (baseline.get("sessions_with_energy_count") or 0) >= 1
    )
    growth_score: Optional[float] = None
    display_score = overall_score
    if baseline_ready and baseline:
        energy_ratio = (e3 / e2) if (e2 and e3 is not None and e2 != 0) else None
        growth_score, _ = compute_growth_score(
            baseline=baseline,
            current_wpm=pace_wpm,
            current_pause_ms=pause_avg_ms,
            current_dynamic_db=dynamic_range_db,
            current_emphasis_per_min=emphasis_spikes_per_min,
            current_energy_ratio=energy_ratio,
            pace_available=pace_available,
            energy_available=energy_available,
        )
        if growth_score is not None:
            display_score = round(
                BLEND_STAGE_WEIGHT * overall_score + BLEND_GROWTH_WEIGHT * growth_score,
                0,
            )
            display_score = int(_clamp(display_score, 0, 100))

    coaching = select_coaching_message(
        pace_wpm, pace_zone,
        pause_avg_ms, pause_zone,
        dynamic_range_db, dynamic_zone,
        emphasis_spikes_per_min, emphasis_zone,
        energy_pattern,
    )

    segments: Dict[str, Any] = {
        "pace": {
            "score": pace_score,
            "zone": pace_zone,
            "raw": raw_wpm,
            "variance_wpm": pace_variance_wpm,
        },
        "pause": {
            "score": pause_score,
            "zone": pause_zone,
            "avg_pause_ms": round(pause_avg_ms, 0),
            "speech_density": round(speech_density * 100),
            "max_pause_s": round(max_pause_s, 2),
        },
        "dynamic": {
            "score": dynamic_score,
            "zone": dynamic_zone,
            "dynamic_range_db": round(dynamic_range_db, 1),
        },
        "emphasis": {
            "score": emphasis_score,
            "zone": emphasis_zone,
            "spikes_per_min": round(emphasis_spikes_per_min, 1),
        },
        "energy": {
            "score": energy_score,
            "zone": "green" if "Declining" not in energy_pattern and energy_pattern not in ("Flat", "—") else "yellow",
            "pattern": energy_pattern,
            "e1": e1,
            "e2": e2,
            "e3": e3,
        },
    }

    return {
        "segments": segments,
        "overall_score": overall_score,
        "stage_score": overall_score,
        "display_score": display_score,
        "growth_score": growth_score,
        "baseline_ready": baseline_ready,
        "session_count": session_count,
        "tier": tier_label(float(display_score)),
        "coaching_message": coaching,
        "pace_available": pace_available,
        "score_completeness": score_completeness,
        "live": {
            "pace_wpm": pace_wpm,
            "pause_avg_ms": round(pause_avg_ms, 0),
            "dynamic_range_db": round(dynamic_range_db, 1),
            "emphasis_per_min": round(emphasis_spikes_per_min, 1),
            "energy_pattern": energy_pattern,
        },
    }
