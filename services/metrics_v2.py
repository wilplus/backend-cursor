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


def compute_metrics_v2(
    wpm: float,
    strength_raw: Optional[float],
    filler_count: int,
    emotion_achieved: bool,
    transcript: str,
    keywords: List[str],
    metric_definitions: List[Dict],
) -> Dict[str, Any]:
    """
    Returns:
    - metrics: { code: { raw, normalized, explanation } }
    - performance_score: 0..1 (average of 5)
    - metric_labels_snapshot: { code: { left_label, right_label } } for storage
    """
    labels = {m["code"]: {"left_label": m.get("left_label", ""), "right_label": m.get("right_label", "")} for m in metric_definitions}

    pace_n = normalize_pace(wpm)
    strength_n = normalize_strength(strength_raw) if strength_raw is not None else 0.5
    fillers_n = normalize_fillers(filler_count)
    emotion_n = normalize_emotion_achieved(emotion_achieved)
    keywords_n = normalize_keywords_used(transcript, keywords or [])

    metrics = {
        "pace": {"raw": wpm, "normalized": pace_n, "explanation": f"WPM {wpm:.0f} (target 120-160)"},
        "strength": {"raw": strength_raw, "normalized": strength_n, "explanation": f"Loudness {strength_raw}" if strength_raw is not None else "Loudness (pending)"},
        "fillers": {"raw": filler_count, "normalized": fillers_n, "explanation": f"{filler_count} fillers"},
        "emotion_achieved": {"raw": emotion_achieved, "normalized": emotion_n, "explanation": "Yes" if emotion_achieved else "No"},
        "keywords_used": {"raw": len([k for k in (keywords or []) if k]), "normalized": keywords_n, "explanation": f"Keywords matched in transcript"},
    }

    performance_score = (pace_n + strength_n + fillers_n + emotion_n + keywords_n) / 5.0
    performance_score = max(0.0, min(1.0, performance_score))

    return {
        "metrics": metrics,
        "performance_score": performance_score,
        "metric_labels_snapshot": labels,
    }
