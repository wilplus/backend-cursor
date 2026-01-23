import re
from typing import Dict, List

# Default filler words/phrases (case-insensitive, whole-word/phrase match)
DEFAULT_FILLERS = ["um", "uh", "like", "you know", "er", "ah", "so"]

def count_fillers(transcript: str, filler_list: List[str] = None) -> Dict:
    """
    Count filler words/phrases in transcript.
    Case-insensitive, whole-word/phrase match, ignores punctuation.
    """
    if filler_list is None:
        filler_list = DEFAULT_FILLERS
    
    # Normalize transcript: lowercase, remove punctuation for matching
    normalized = transcript.lower()
    # Remove punctuation but keep spaces
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    
    breakdown = {}
    total_count = 0
    
    for filler in filler_list:
        # For phrases like "you know", match as phrase
        if " " in filler:
            # Count phrase occurrences (word boundaries)
            pattern = r'\b' + re.escape(filler.lower()) + r'\b'
            count = len(re.findall(pattern, normalized))
        else:
            # Single word: match whole word only
            pattern = r'\b' + re.escape(filler.lower()) + r'\b'
            count = len(re.findall(pattern, normalized))
        
        if count > 0:
            breakdown[filler] = count
            total_count += count
    
    return {
        "breakdown": breakdown,
        "total": total_count
    }

def compute_wpm(transcript: str, duration_seconds: float) -> float:
    """
    Compute words per minute.
    WPM = word_count / (duration_seconds / 60)
    """
    if duration_seconds <= 0:
        return 0.0
    
    word_count = len(transcript.split())
    wpm = word_count / (duration_seconds / 60.0)
    
    return round(wpm, 2)

def compute_trend(current_value: float, previous_value: float, threshold: float) -> str:
    """
    Compute trend direction: ↑ (up), ↓ (down), → (flat)
    Based on threshold comparison.
    """
    delta = current_value - previous_value
    
    if abs(delta) >= threshold:
        if delta > 0:
            return "↑"
        else:
            return "↓"
    else:
        return "→"

def compute_trend_sentence(
    current_wpm: float,
    current_filler_count: int,
    previous_wpm: float = None,
    previous_filler_count: int = None
) -> str:
    """
    Compute trend sentence in format:
    "Pacing [↑/↓/→] ([±X] WPM), fillers [↑/↓/→] ([±X])"
    
    Returns None if insufficient data (<2 prior recordings).
    """
    if previous_wpm is None or previous_filler_count is None:
        return None
    
    wpm_delta = current_wpm - previous_wpm
    filler_delta = current_filler_count - previous_filler_count
    
    wpm_trend = compute_trend(current_wpm, previous_wpm, threshold=10.0)
    filler_trend = compute_trend(current_filler_count, previous_filler_count, threshold=3.0)
    
    wpm_sign = "+" if wpm_delta >= 0 else ""
    filler_sign = "+" if filler_delta >= 0 else ""
    
    return f"Pacing {wpm_trend} ({wpm_sign}{wpm_delta:.1f} WPM), fillers {filler_trend} ({filler_sign}{filler_delta})"
