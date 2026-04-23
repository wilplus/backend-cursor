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


# ---------------------------------------------------------------------------
# Phase 3 hook: diagnose a completed session and persist the suggestion.
# Gated upstream by Config.DIAGNOSE_SESSION_STATE_ENABLED.
# ---------------------------------------------------------------------------


def _coerce_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build_session_metrics(
    *,
    wpm: Optional[float],
    sniper_metrics: Optional[dict],
    filler_count: Optional[int],
) -> SessionMetrics:
    """Assemble a `SessionMetrics` from the values available at completion time.

    `sniper_metrics` is the dict returned by `db.get_session_sniper_metrics`;
    missing or non-numeric fields are coerced to None without raising.
    """
    sniper = sniper_metrics or {}
    return SessionMetrics(
        wpm=_coerce_float(wpm),
        pause_ms=_coerce_float(sniper.get("pause_ms")),
        filler_count=_coerce_int(filler_count),
        dynamic_db=_coerce_float(sniper.get("dynamic_db")),
    )


def diagnose_and_persist_session(
    *,
    session_id: str,
    user_id: str,
    wpm: Optional[float],
    sniper_metrics: Optional[dict],
    filler_count: Optional[int],
    db=None,
) -> Optional[BehavioralProfile]:
    """Diagnose a completed session and persist `ai_suggested_*` on v2_sessions.

    Returns the diagnosed profile. Caller is responsible for gating on the
    `DIAGNOSE_SESSION_STATE_ENABLED` config flag and swallowing exceptions;
    this function raises on DB errors so the caller can log appropriately.

    `db` is injectable for tests. In production the shared singleton from
    `services.db` is used.
    """
    if db is None:
        from services.db import db as _db  # lazy to avoid bootstrap coupling
        db = _db

    metrics = build_session_metrics(
        wpm=wpm,
        sniper_metrics=sniper_metrics,
        filler_count=filler_count,
    )
    profile = diagnose_session_state(metrics)

    task_id: Optional[str] = None
    rows = db.v2_get_next_active_task_pool_template(
        target_profile=profile.value,
        level=1,
        limit=1,
        is_behavioral=True,
    )
    if rows:
        raw_id = rows[0].get("id")
        if raw_id:
            task_id = str(raw_id)

    db.v2_update_session(session_id, user_id, {
        "ai_suggested_profile": profile.value,
        "ai_suggested_task_id": task_id,
    })
    return profile
