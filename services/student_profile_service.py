from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.db import db


@dataclass(frozen=True)
class StageRule:
    stage: int
    min_sessions: int
    min_score_100: float
    max_score_100: float


STAGE_RULES: List[StageRule] = [
    StageRule(stage=1, min_sessions=1, min_score_100=0, max_score_100=45),
    StageRule(stage=2, min_sessions=3, min_score_100=45, max_score_100=60),
    StageRule(stage=3, min_sessions=6, min_score_100=60, max_score_100=72),
    StageRule(stage=4, min_sessions=10, min_score_100=72, max_score_100=83),
    StageRule(stage=5, min_sessions=15, min_score_100=83, max_score_100=101),
]


def _score_100_from_session_row(row: Dict[str, Any]) -> Optional[float]:
    sfd = row.get("score_for_display")
    if sfd is not None:
        try:
            return float(sfd)
        except (TypeError, ValueError):
            pass
    score_01 = row.get("score")
    if score_01 is None:
        return None
    try:
        raw = float(score_01)
    except (TypeError, ValueError):
        return None
    if raw > 1.0:
        return raw
    return raw * 100.0


def _ema_last_n(values: List[float], n: int = 3) -> Optional[float]:
    vals = [float(v) for v in values if v is not None][-n:]
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    alpha = 2.0 / (len(vals) + 1.0)
    ema = vals[0]
    for v in vals[1:]:
        ema = alpha * v + (1.0 - alpha) * ema
    return ema


def _target_stage(session_count: int, ema_score_100: Optional[float]) -> int:
    if ema_score_100 is None:
        return 1
    target = 1
    for rule in STAGE_RULES:
        if session_count >= rule.min_sessions and rule.min_score_100 <= ema_score_100 < rule.max_score_100:
            target = rule.stage
    return target


def _safe_float(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _classify_behavioral_profile(
    *,
    ema_score_100: Optional[float],
    latest_wpm: Optional[float],
    latest_context_fit_01: Optional[float],
    latest_self_rating_1_5: Optional[int],
) -> tuple[str, str]:
    score = ema_score_100 or 0.0
    context_fit = latest_context_fit_01
    wpm = latest_wpm
    self_rating = latest_self_rating_1_5

    if score >= 83 and (context_fit is None or context_fit >= 0.65):
        label = "The Master"
        why = "High recent score and stable task-context alignment suggest advanced control."
    elif (wpm is not None and wpm >= 150) and score < 72:
        label = "The Stressor"
        why = "Fast pace with sub-threshold performance suggests stress-driven delivery instability."
    elif context_fit is not None and context_fit < 0.45 and score >= 55:
        label = "The Drifter"
        why = "Delivery metrics are reasonable, but transcript-to-task fit is weak."
    else:
        label = "The Overwhelmed"
        why = "Both delivery consistency and task adherence need reinforcement."

    # Optional psychological modifier from self-rating mismatch.
    if self_rating is not None and score > 0:
        normalized_self = (float(self_rating) / 5.0) * 100.0
        gap = normalized_self - score
        if gap <= -20:
            why += " Self-rating is significantly lower than measured score (underconfident pattern)."
        elif gap >= 20:
            why += " Self-rating is significantly higher than measured score (overconfident pattern)."
    return label, why


def refresh_student_profile_state(user_id: str) -> Dict[str, Any]:
    sessions_res = (
        db.client.table("v2_sessions")
        .select("id, score, score_for_display, score_components, completed_at, created_at")
        .eq("user_id", user_id)
        .eq("status", "completed")
        .order("completed_at", desc=False)
        .limit(30)
        .execute()
    )
    sessions = sessions_res.data or []
    score_hist = [_score_100_from_session_row(s) for s in sessions]
    score_hist = [s for s in score_hist if s is not None]
    session_count = len(sessions)
    ema_score_100 = _ema_last_n(score_hist, n=3)

    profile = db.get_sniper_profile(user_id) or {}
    current_stage = _safe_int(profile.get("computed_stage") or profile.get("coach_override_stage") or 1, 1)
    consec_below = _safe_int(profile.get("consecutive_below_threshold"), 0)
    target = _target_stage(session_count, ema_score_100)

    if target >= current_stage:
        computed_stage = target
        consec_below = 0
    else:
        consec_below += 1
        if consec_below >= 2:
            computed_stage = target
            consec_below = 0
        else:
            computed_stage = current_stage

    latest_session = sessions[-1] if sessions else {}
    latest_context_fit_01 = None
    try:
        context_component = (((latest_session.get("score_components") or {}).get("components") or {}).get("context") or {})
        latest_context_fit_01 = _safe_float(context_component.get("normalized"))
    except Exception:
        latest_context_fit_01 = None

    latest_wpm = None
    latest_self_rating = None
    if latest_session.get("id"):
        sm = db.get_session_sniper_metrics(str(latest_session["id"])) or {}
        latest_wpm = _safe_float(sm.get("wpm"))
        latest_self_rating = _safe_int(sm.get("student_rating_1_10"), 0) or None

    label, why = _classify_behavioral_profile(
        ema_score_100=ema_score_100,
        latest_wpm=latest_wpm,
        latest_context_fit_01=latest_context_fit_01,
        latest_self_rating_1_5=latest_self_rating,
    )

    updated = db.upsert_student_profile_fields(
        user_id,
        {
            "computed_stage": int(max(1, min(5, computed_stage))),
            "consecutive_below_threshold": int(max(0, consec_below)),
            "behavioral_profile": label,
            "behavioral_profile_justification": why,
            "session_count": int(max(session_count, _safe_int(profile.get("session_count"), 0))),
        },
    )
    return updated

