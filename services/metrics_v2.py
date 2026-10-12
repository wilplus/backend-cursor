"""
V2: Exactly 5 metrics (pace, strength, fillers, emotion_achieved, keywords_used).
Normalize to 0..1; performance_score = average (or weighted). Snapshot labels for history.
"""
from typing import Dict, Any, Optional

# Pace: target band 120-160 WPM => high score
PACE_TARGET_LOW = 120
PACE_TARGET_HIGH = 160
PACE_MIN = 60
PACE_MAX = 220


def _smoothstep(t: float) -> float:
    """Smoothstep for 0..1 easing."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def normalize_pace(wpm: float) -> float:
    """0..1; high in 120-160 band."""
    if wpm <= 0:
        return 0.5
    if PACE_TARGET_LOW <= wpm <= PACE_TARGET_HIGH:
        return 1.0
    if wpm < PACE_TARGET_LOW:
        t = (wpm - PACE_MIN) / (PACE_TARGET_LOW - PACE_MIN) if PACE_TARGET_LOW > PACE_MIN else 0
        return _smoothstep(max(0, t))
    t = (PACE_MAX - wpm) / (PACE_MAX - PACE_TARGET_HIGH) if PACE_MAX > PACE_TARGET_HIGH else 0
    return _smoothstep(max(0, t))


def normalize_fillers(filler_count: int) -> float:
    """High when <=3 fillers; smoothstep decrease after that."""
    if filler_count <= 3:
        return 1.0
    # Smooth decay: 4 -> ~0.9, 10 -> ~0.3, etc.
    t = (10.0 - min(filler_count, 15)) / 10.0
    return _smoothstep(max(0.0, min(1.0, t)))


def compute_recording_performance_score(
    center_hold_ratio: Optional[float],
    filler_count: int,
    wpm: float,
) -> Dict[str, Any]:
    """
    Unified performance score formula for any recording step.

    Primary path (center_hold_ratio available):
        base = center_hold_ratio * 100, then penalise 3 pts per filler word.
    Fallback (no center_hold_ratio):
        base = 60% pace_normalized + 40% fillers_normalized.
    Product rule: any fillers cap score below 100%.

    Returns a dict with score_01 (0..1) and debug fields so callers can
    store a consistent scoring_debug regardless of which recording it is.
    """
    filler_count = int(filler_count)
    if center_hold_ratio is not None:
        score_source = "center_hold_payload"
        base_score_100 = round(center_hold_ratio * 100.0)
        penalty_points = 3 * filler_count
        final_score_100 = max(0.0, min(100.0, float(base_score_100 - penalty_points)))
    else:
        score_source = "transcript_metrics_fallback"
        pace_n = normalize_pace(wpm)
        fillers_n = normalize_fillers(filler_count)
        base_score_100 = round(((0.6 * pace_n) + (0.4 * fillers_n)) * 100.0)
        penalty_points = 0
        final_score_100 = max(0.0, min(100.0, float(base_score_100)))
    if filler_count > 0 and final_score_100 >= 100.0:
        final_score_100 = 99.0
    return {
        "score_01": final_score_100 / 100.0,
        "score_source": score_source,
        "center_hold_ratio": center_hold_ratio,
        "base_score_100": base_score_100,
        "filler_count": filler_count,
        "penalty_points": penalty_points,
        "final_score_01": final_score_100 / 100.0,
    }



# ── Layer-cross drift guard (Phase 17) ──────────────────────────────────────


# Maximum allowed gap between the B6 Master Score (0..1) and the
# D1/D2 classifier confidence (0..1) before we flag the session for
# admin review. Tuned at 0.40 per the constitution: that's a 40-
# percentage-point disagreement, which historically only happens
# when one side glitched (transcript missing, classifier model
# regressed, etc.) rather than legitimate noise.
DEFAULT_DRIFT_THRESHOLD = 0.40


def detect_classifier_drift(
    *,
    performance_score: Optional[float],
    classifier_confidence: Optional[float],
    threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> Dict[str, Any]:
    """Compare B6 against the D1/D2 classifier confidence.

    Returns a diagnostic dict the caller can stuff onto the session
    row (or use to decide whether to flip a `needs_admin_review`
    bit). Both inputs are expected in [0, 1] — pass the classifier's
    own confidence ([charisma|stress]_snippets.classifier_confidence)
    NOT a raw probability.

    Returns ``needs_admin_review = False`` when either side is None
    (can't drift if you can't compare) — the caller can decide
    whether NULL inputs themselves warrant admin attention via a
    separate check.

    The threshold default (0.40) matches the constitution. Callers
    can raise it (more permissive) or lower it (catch finer drift)
    by passing ``threshold``.
    """
    if performance_score is None or classifier_confidence is None:
        return {
            "performance_score": performance_score,
            "classifier_confidence": classifier_confidence,
            "deviation": None,
            "threshold": threshold,
            "needs_admin_review": False,
            "reason": "missing_input",
        }
    try:
        ps = float(performance_score)
        cc = float(classifier_confidence)
    except (TypeError, ValueError):
        return {
            "performance_score": performance_score,
            "classifier_confidence": classifier_confidence,
            "deviation": None,
            "threshold": threshold,
            "needs_admin_review": False,
            "reason": "uncastable",
        }
    deviation = abs(ps - cc)
    needs_review = deviation > threshold
    return {
        "performance_score": ps,
        "classifier_confidence": cc,
        "deviation": round(deviation, 4),
        "threshold": threshold,
        "needs_admin_review": needs_review,
        "reason": "drift_above_threshold" if needs_review else "within_threshold",
    }
