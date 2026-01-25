"""Service for calculating performance scores from post-recording answers"""
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Filler threshold for normalization (adjust based on your data)
FILLER_THRESHOLD = 10


def normalize_scores(
    filler_word_count: int,
    pacing_score: float,
    attitude_score: float,
    q1_answer: str,
    q2_answer: str,
) -> Dict[str, float]:
    """
    Normalize all scores to 0.0-1.0 range
    
    Args:
        filler_word_count: Number of filler words
        pacing_score: Already normalized pacing score (0.0-1.0)
        attitude_score: Already normalized attitude score (0.0-1.0)
        q1_answer: Scale answer "1"-"5"
        q2_answer: Binary answer "YES" or "NO"
    
    Returns:
        Dictionary with normalized scores
    """
    # Filler score: lower is better (0 fillers = 1.0, threshold fillers = 0.0)
    filler_score = max(0.0, min(1.0, 1.0 - (filler_word_count / FILLER_THRESHOLD)))
    
    # Pacing and attitude already normalized (0.0-1.0)
    # Clamp to ensure they're in range
    pacing_score = max(0.0, min(1.0, pacing_score))
    attitude_score = max(0.0, min(1.0, attitude_score))
    
    # Reflection score: from scale answer (1-5) → (0.0-1.0)
    # "1" → 0.0, "5" → 1.0
    try:
        scale_value = int(q1_answer) if q1_answer.isdigit() else 3
        scale_value = max(1, min(5, scale_value))  # Clamp to 1-5
        reflection_score = (scale_value - 1) / 4.0  # (1→0.0, 5→1.0)
    except (ValueError, TypeError):
        reflection_score = 0.5  # Default to middle if invalid
    
    # Awareness bonus: YES = 1.0, NO = 0.0
    awareness_bonus = 1.0 if q2_answer and q2_answer.upper() == "YES" else 0.0
    
    return {
        'filler_score': filler_score,
        'pacing_score': pacing_score,
        'attitude_score': attitude_score,
        'reflection_score': reflection_score,
        'awareness_bonus': awareness_bonus,
    }


def calculate_performance_score(normalized: Dict[str, float]) -> float:
    """
    Core performance score (weighted average)
    
    Weights:
    - 30% filler score
    - 25% pacing score
    - 25% attitude score
    - 20% reflection score
    """
    performance = (
        0.30 * normalized['filler_score'] +
        0.25 * normalized['pacing_score'] +
        0.25 * normalized['attitude_score'] +
        0.20 * normalized['reflection_score']
    )
    
    return max(0.0, min(1.0, performance))


def calculate_bonuses(
    performance: float,
    initial_mood: str,
    filler_word_count: int,
    awareness_bonus: float,
    previous_performance: Optional[float] = None,
    user_streak: int = 0,
) -> Dict[str, float]:
    """
    Calculate performance bonuses
    
    Bonuses:
    - Resilience: Negative mood + zero fillers (0.05)
    - Awareness: User noticed fillers (0.03)
    - Progress: Improved from last time (up to 0.05)
    - Streak: 3+ consecutive sessions (0.05, optional)
    """
    bonuses = {}
    
    # Resilience bonus: Negative mood + zero fillers
    if initial_mood == "negative" and filler_word_count == 0:
        bonuses['resilience'] = 0.05
    
    # Awareness bonus: User noticed fillers (answered YES)
    if awareness_bonus == 1.0:
        bonuses['awareness'] = 0.03
    
    # Progress bonus: Improved from last time
    if previous_performance is not None and performance > previous_performance:
        progress_diff = performance - previous_performance
        bonuses['progress'] = min(0.05, progress_diff * 0.5)  # Scale down progress bonus
    
    # Streak bonus: 3+ consecutive sessions (optional)
    if user_streak >= 3:
        bonuses['streak'] = 0.05
    
    return bonuses


def calculate_final_kpi(performance: float, bonuses: Dict[str, float]) -> float:
    """
    Final KPI = performance + bonuses (capped at 1.0)
    """
    total_bonus = sum(bonuses.values())
    final_kpi = min(1.0, performance + total_bonus)
    
    return final_kpi


def calculate_pacing_score(wpm: float) -> float:
    """
    Calculate normalized pacing score from WPM
    
    Optimal range: 120-160 WPM
    Too slow (< 100): lower score
    Too fast (> 180): lower score
    """
    if wpm <= 0:
        return 0.5  # Default
    
    # Optimal range: 120-160 WPM = 1.0
    # Below 100 or above 180 = 0.0
    # Linear interpolation
    
    if 120 <= wpm <= 160:
        return 1.0
    elif wpm < 120:
        # Below 120: linear from 0.0 (at 60) to 1.0 (at 120)
        return max(0.0, min(1.0, (wpm - 60) / 60.0))
    else:
        # Above 160: linear from 1.0 (at 160) to 0.0 (at 220)
        return max(0.0, min(1.0, (220 - wpm) / 60.0))


def calculate_attitude_score(classification: str, confidence: str) -> float:
    """
    Calculate normalized attitude score from classification and confidence
    
    Classification: "confident", "uncertain", "nervous", etc.
    Confidence: "high", "medium", "low"
    """
    # Classification scores
    classification_scores = {
        "confident": 1.0,
        "uncertain": 0.5,
        "nervous": 0.3,
    }
    
    # Confidence scores
    confidence_scores = {
        "high": 1.0,
        "medium": 0.6,
        "low": 0.3,
    }
    
    class_score = classification_scores.get(classification.lower(), 0.5)
    conf_score = confidence_scores.get(confidence.lower(), 0.5)
    
    # Average of classification and confidence
    attitude_score = (class_score + conf_score) / 2.0
    
    return max(0.0, min(1.0, attitude_score))
