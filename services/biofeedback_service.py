"""
Biofeedback "dartboard" engine: axis profiles and scoring config per theme.
Client uses these to show real-time ball position and compute time-in-center KPI.
"""
from typing import Dict, List, Any

# Theme codes (must match question_service.THEMES)
THEMES = [
    "presence_grounding",
    "clarity_simplicity",
    "pacing_rhythm",
    "energy_conviction",
    "confidence_comfort",
    "structure_organization",
    "story_narrative",
]

# Default scoring config (used by all profiles unless overridden)
DEFAULT_SCORING = {
    "update_hz": 20,
    "window_ms": 2000,
    "center_threshold": 0.6,
}

# Axis definitions (metric = client-side: loudness_db, speech_rate_proxy, steadiness_proxy, etc.)
AXIS_STRENGTH = {
    "code": "strength",
    "label_left": "weak",
    "label_right": "strong",
    "metric": "loudness_db",
    "target": {"center": -25, "radius": 6},
}
AXIS_PACE = {
    "code": "pace",
    "label_left": "slow",
    "label_right": "fast",
    "metric": "speech_rate_proxy",
    "target": {"center": 4.0, "radius": 1.0},
}
AXIS_STEADINESS = {
    "code": "steadiness",
    "label_left": "uneven",
    "label_right": "steady",
    "metric": "steadiness_proxy",
    "target": {"center": 0.5, "radius": 0.25},
}

# Theme -> default 2-axis profile (v1). Client normalizes to [-1,1] per axis; ball = (nx, ny); center = (0,0).
BIOFEEDBACK_PROFILES_BY_THEME: Dict[str, Dict[str, Any]] = {
    "pacing_rhythm": {
        "axes": [AXIS_PACE, AXIS_STRENGTH],
        "scoring": DEFAULT_SCORING,
    },
    "presence_grounding": {
        "axes": [AXIS_STRENGTH, AXIS_STEADINESS],
        "scoring": DEFAULT_SCORING,
    },
    "clarity_simplicity": {
        "axes": [AXIS_STRENGTH, AXIS_PACE],
        "scoring": DEFAULT_SCORING,
    },
    "energy_conviction": {
        "axes": [AXIS_STRENGTH, AXIS_PACE],
        "scoring": DEFAULT_SCORING,
    },
    "confidence_comfort": {
        "axes": [AXIS_STRENGTH, AXIS_STEADINESS],
        "scoring": DEFAULT_SCORING,
    },
    "structure_organization": {
        "axes": [AXIS_PACE, AXIS_STRENGTH],
        "scoring": DEFAULT_SCORING,
    },
    "story_narrative": {
        "axes": [AXIS_PACE, AXIS_STRENGTH],
        "scoring": DEFAULT_SCORING,
    },
}

# Fallback when theme is unknown or null
DEFAULT_BIOFEEDBACK_PROFILE = {
    "axes": [AXIS_STRENGTH, AXIS_PACE],
    "scoring": DEFAULT_SCORING,
}


def get_biofeedback_profile(theme_code: str = None) -> Dict[str, Any]:
    """
    Return the biofeedback_profile for the given theme (for POST /session/start).
    Keys: axes (list), scoring (dict). Use default profile if theme_code is missing or unknown.
    """
    if theme_code and theme_code in BIOFEEDBACK_PROFILES_BY_THEME:
        return BIOFEEDBACK_PROFILES_BY_THEME[theme_code].copy()
    return DEFAULT_BIOFEEDBACK_PROFILE.copy()
