"""
V2: Exactly 5 metrics (pace, strength, fillers, emotion_achieved, keywords_used).
Normalize to 0..1; performance_score = average (or weighted). Snapshot labels for history.
"""
import re
from typing import Dict, List, Any, Optional

# Fixed metric codes
METRIC_CODES = ["pace", "strength", "fillers", "emotion_achieved", "keywords_used"]

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


def normalize_strength(rms_or_db: float) -> float:
    """
    strength: from audio loudness (RMS or dB). Normalize to 0..1.
    Assume input is in a reasonable range; center around -25 dB => 1.0, very quiet => 0.
    """
    # Heuristic: if value looks like dB (e.g. -40 to 0), map -25 as center, radius ~15
    if rms_or_db is None:
        return 0.5
    center = -25.0
    radius = 15.0
    t = (float(rms_or_db) - (center - radius)) / (2 * radius)
    return _smoothstep(max(0.0, min(1.0, t)))


def normalize_fillers(filler_count: int) -> float:
    """High when <=3 fillers; smoothstep decrease after that."""
    if filler_count <= 3:
        return 1.0
    # Smooth decay: 4 -> ~0.9, 10 -> ~0.3, etc.
    t = (10.0 - min(filler_count, 15)) / 10.0
    return _smoothstep(max(0.0, min(1.0, t)))


def normalize_emotion_achieved(yes_no_answer: bool) -> float:
    """1.0 if yes, 0.0 if no."""
    return 1.0 if yes_no_answer else 0.0


def normalize_keywords_used(transcript: str, keywords: List[str], min_match: int = 2) -> float:
    """
    Score 1 if >= min_match of the 3 keywords appear (case-insensitive, word boundary).
    Else 0 (or optional easing).
    """
    if not transcript or not keywords:
        return 0.0
    normalized = transcript.lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    seen = 0
    for kw in keywords[:3]:
        if not kw:
            continue
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, normalized):
            seen += 1
    if seen >= min_match:
        return 1.0
    return 0.0


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


# Performance profile: label thresholds (aligned with normalize_pace / normalize_fillers)
# Pace: target band 120-160 = optimal; clearly below/above get labels for coaching
PACE_LEVEL_TOO_SLOW_BELOW = 110   # wpm < this -> too_slow
PACE_LEVEL_TOO_FAST_ABOVE = 170   # wpm > this -> too_fast
FILLER_LEVEL_LOW_MAX = 3         # filler_count <= this -> low
FILLER_LEVEL_MEDIUM_MAX = 8      # 4..8 -> medium, >8 -> high


def build_recording_1_performance_profile(wpm: float, filler_count: int) -> Dict[str, Any]:
    """
    Deterministic labels from recording-1 metrics for coaching (recurring-issue detection, future task weighting).
    Only pace_level and filler_level; no LLM. JSON includes version for future extension.
    """
    if wpm < PACE_LEVEL_TOO_SLOW_BELOW:
        pace_level = "too_slow"
    elif wpm > PACE_LEVEL_TOO_FAST_ABOVE:
        pace_level = "too_fast"
    else:
        pace_level = "optimal"

    filler_count = max(0, int(filler_count))
    if filler_count <= FILLER_LEVEL_LOW_MAX:
        filler_level = "low"
    elif filler_count <= FILLER_LEVEL_MEDIUM_MAX:
        filler_level = "medium"
    else:
        filler_level = "high"

    return {
        "version": 1,
        "pace_level": pace_level,
        "filler_level": filler_level,
    }


def compute_metrics_v2(
    wpm: Optional[float],
    strength_raw: Optional[float],
    filler_count: Optional[int],
    emotion_achieved: Optional[bool],
    transcript: Optional[str],
    keywords: Optional[List[str]],
    metric_definitions: List[Dict],
) -> Dict[str, Any]:
    """B6 — the canonical Master Score (see docs/ACOUSTIC-METRICS-INVENTORY.md).

    Five components: pace, strength, fillers, emotion_achieved,
    keywords_used. Each normalised to 0..1.

    NULL handling (Phase 17 — replaces the previous "substitute 0.5"
    behaviour):
        Missing component → its weight is REDISTRIBUTED proportionally
        across the components that DO carry signal. A session with
        complete pace + fillers + keywords but missing strength +
        emotion runs as `(pace + fillers + keywords) / 3` rather than
        `(pace + 0.5 + fillers + 0 + keywords) / 5`.
        When every component is missing, performance_score = None.

    Returns:
        {
          metrics: { code: { raw, normalized, explanation, is_real, weight } },
          performance_score: float | None,   # 0..1, None when no signal
          weights_used: { code: weight },    # the redistributed weights
          components_with_signal: int,       # 0..5
          metric_labels_snapshot: { code: { left_label, right_label } },
        }
    """
    labels = {
        m["code"]: {
            "left_label": m.get("left_label", ""),
            "right_label": m.get("right_label", ""),
        }
        for m in (metric_definitions or [])
    }

    # ── Per-component evaluation ──────────────────────────────────
    # Each tuple: (normalized_value, is_real_signal, raw_for_display,
    #              explanation).
    components: Dict[str, Dict[str, Any]] = {}

    # Pace — real when wpm > 0. wpm == None or <= 0 means no signal;
    # normalize_pace's legacy 0.5-fallback path is bypassed via the
    # is_real flag.
    if wpm is not None and float(wpm) > 0:
        components["pace"] = {
            "normalized": normalize_pace(float(wpm)),
            "is_real": True,
            "raw": wpm,
            "explanation": f"WPM {float(wpm):.0f} (target 120-160)",
        }
    else:
        components["pace"] = {
            "normalized": None, "is_real": False, "raw": wpm,
            "explanation": "Pace (no signal)",
        }

    # Strength — real when an rms/dB value was actually measured.
    if strength_raw is not None:
        components["strength"] = {
            "normalized": normalize_strength(strength_raw),
            "is_real": True,
            "raw": strength_raw,
            "explanation": f"Loudness {strength_raw}",
        }
    else:
        components["strength"] = {
            "normalized": None, "is_real": False, "raw": None,
            "explanation": "Loudness (pending)",
        }

    # Fillers — real when filler_count is known (even zero is a real
    # measurement). Distinct from "the user happened to have 0
    # fillers" vs "the metrics pipeline didn't run".
    if filler_count is not None:
        fc = int(filler_count)
        components["fillers"] = {
            "normalized": normalize_fillers(fc),
            "is_real": True,
            "raw": fc,
            "explanation": f"{fc} fillers",
        }
    else:
        components["fillers"] = {
            "normalized": None, "is_real": False, "raw": None,
            "explanation": "Fillers (pending)",
        }

    # Emotion achieved — real when the post-recording yes/no answer
    # was captured. None means the question wasn't asked / answered.
    if emotion_achieved is not None:
        components["emotion_achieved"] = {
            "normalized": normalize_emotion_achieved(bool(emotion_achieved)),
            "is_real": True,
            "raw": bool(emotion_achieved),
            "explanation": "Yes" if emotion_achieved else "No",
        }
    else:
        components["emotion_achieved"] = {
            "normalized": None, "is_real": False, "raw": None,
            "explanation": "Emotion check (not answered)",
        }

    # Keywords — real when both transcript AND a non-empty keyword
    # list are present. Otherwise we can't score it.
    kw_list = [k for k in (keywords or []) if k]
    if transcript and kw_list:
        components["keywords_used"] = {
            "normalized": normalize_keywords_used(transcript, kw_list),
            "is_real": True,
            "raw": len(kw_list),
            "explanation": "Keywords matched in transcript",
        }
    else:
        components["keywords_used"] = {
            "normalized": None, "is_real": False, "raw": len(kw_list),
            "explanation": "Keywords (no transcript or no list)",
        }

    # ── Weight redistribution ────────────────────────────────────
    real_codes = [k for k, v in components.items() if v["is_real"]]
    weights_used: Dict[str, float] = {}
    if real_codes:
        # Equal weight among real components (pre-Phase-17 weights
        # were already 1/5 each, so this preserves intent when all
        # five are real).
        equal_weight = 1.0 / len(real_codes)
        for code in real_codes:
            weights_used[code] = equal_weight
            components[code]["weight"] = equal_weight
        performance_score = sum(
            components[code]["normalized"] * weights_used[code]
            for code in real_codes
        )
        performance_score = max(0.0, min(1.0, performance_score))
    else:
        performance_score = None

    # Non-real components carry weight 0 in the output so callers
    # rendering the metric strip can distinguish "weighted in" from
    # "not weighted in".
    for code, v in components.items():
        v.setdefault("weight", 0.0)

    return {
        "metrics": components,
        "performance_score": performance_score,
        "weights_used": weights_used,
        "components_with_signal": len(real_codes),
        "metric_labels_snapshot": labels,
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
