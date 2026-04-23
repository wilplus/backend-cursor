"""Deterministic single-session classifier for the recommendation engine.

`diagnose_session_state(metrics)` maps one session's acoustic telemetry to a
`BehavioralProfile` using the waterfall locked on 2026-04-23:

    1. WPM > 170                         -> Stressor
    2. WPM < 120                         -> Overwhelmed
    3. filler_count > 5  (120-170 band)  -> Drifter
    4. dynamic_db >= healthy_threshold   -> Master
       else (flat / monotone)            -> Drifter

This classifier operates on a single recording. It is distinct from
`student_profile_service._classify_behavioral_profile`, which classifies a
student over time via EMA. The two share labels but may disagree on an
individual student; the coach arbitrates via the admin dashboard.

Not wired into the session-completion pipeline yet (Phase 3, flag-gated).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.behavioral_profiles import BehavioralProfile


# TODO(artur): calibrate against live acoustic logs. Placeholder dB value
# until we have enough real sessions to set a defensible threshold.
DYNAMIC_DB_HEALTHY_THRESHOLD: float = 6.0

# Waterfall thresholds (locked 2026-04-23).
WPM_STRESSOR_MIN_EXCLUSIVE: float = 170.0
WPM_OVERWHELMED_MAX_EXCLUSIVE: float = 120.0
FILLER_DRIFTER_MIN_EXCLUSIVE: int = 5


@dataclass(frozen=True)
class SessionMetrics:
    """Acoustic telemetry for one recording.

    Fields mirror the keys emitted by `services.audio_metrics.analyze_audio`
    plus `filler_count` from the transcript-processing layer.
    """

    wpm: Optional[float] = None
    pause_ms: Optional[float] = None
    filler_count: Optional[int] = None
    dynamic_db: Optional[float] = None
    pitch_st: Optional[float] = None  # reserved; not in the current waterfall


def diagnose_session_state(
    metrics: SessionMetrics,
    *,
    dynamic_db_healthy_threshold: float = DYNAMIC_DB_HEALTHY_THRESHOLD,
) -> BehavioralProfile:
    """Classify a single session's telemetry into a behavioral profile."""
    wpm = metrics.wpm

    if wpm is None:
        return BehavioralProfile.DRIFTER

    if wpm > WPM_STRESSOR_MIN_EXCLUSIVE:
        return BehavioralProfile.STRESSOR

    if wpm < WPM_OVERWHELMED_MAX_EXCLUSIVE:
        return BehavioralProfile.OVERWHELMED

    filler_count = metrics.filler_count if metrics.filler_count is not None else 0
    if filler_count > FILLER_DRIFTER_MIN_EXCLUSIVE:
        return BehavioralProfile.DRIFTER

    dynamic_db = metrics.dynamic_db
    if dynamic_db is None or dynamic_db < dynamic_db_healthy_threshold:
        return BehavioralProfile.DRIFTER

    return BehavioralProfile.MASTER
