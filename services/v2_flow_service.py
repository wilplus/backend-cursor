"""
V2 flow helpers: task_score and warm-up / focus task selection by score bands.
"""
from typing import Dict, List, Any, Optional

# Task score: average of 3 components (each 0..1)
# Q1: Do you feel more like? good=1, not great=0
# Q2: How ready is your body and mind to present? 1..10 → 0.1..1
# Q3: Do you want to be guided? yes/guide me=0, no/I will choose=1


def compute_task_score(mood: float, readiness: int, mode_preference: int) -> float:
    """
    Q1 (mood): good = +1, not great = 0 (frontend sends 1 or 0; float rounded)
    Q2 (readiness): 1..10 → 0.1 to 1 points (readiness/10)
    Q3 (mode_preference): yes guide me = 0, no I will choose = +1
    task_score = (c1 + c2 + c3) / 3, clamped 0..1.
    """
    # c1: 0 or 1 (good=1, not great=0)
    m = mood if mood is not None else 0.5
    c1 = 1.0 if float(m) >= 0.5 else 0.0
    # c2: 1..10 → 0.1..1
    r = max(1, min(10, int(readiness) if readiness is not None else 5))
    c2 = r / 10.0
    # c3: guide me=0, I will choose=1
    c3 = 1.0 if mode_preference == 1 else 0.0
    raw = (c1 + c2 + c3) / 3.0
    return max(0.0, min(1.0, raw))


def select_warm_up_task(
    student_last_score: Optional[float],
    available_warm_ups: List[Dict],
) -> Optional[Dict]:
    """
    Select warm-up task based on student's last performance_score_end.
    Rule 1: Eligible = warm-ups with max_performance_score >= student's last score.
    Rule 2: Among eligible, closest max_performance_score to student's score (within ±0.03).
    Rule 3: Random choice if multiple within tolerance.
    Rule 4: First-time (no score): easiest = highest max_performance_score (typically 1.0).
    Fallback: if student scored above all warm-ups, return hardest (lowest max).
    """
    import random
    TOLERANCE = 0.03
    if not available_warm_ups:
        return None

    def _max_score(w: Dict) -> float:
        v = w.get("max_performance_score")
        if v is None:
            return 1.0
        return float(v)

    # CASE 1: First-time student (no previous score)
    if student_last_score is None:
        return max(available_warm_ups, key=_max_score)

    # CASE 2: Returning student — filter eligible (max_score >= student's score)
    eligible = [w for w in available_warm_ups if _max_score(w) >= student_last_score]

    # Fallback: student scored too high for all warm-ups → hardest (lowest max)
    if not eligible:
        return min(available_warm_ups, key=_max_score)

    # Closest match score among eligible
    closest_w = min(eligible, key=lambda w: abs(_max_score(w) - student_last_score))
    closest_score = _max_score(closest_w)

    # All warm-ups within ±3% of closest score
    within_tolerance = [
        w for w in eligible
        if abs(_max_score(w) - closest_score) <= TOLERANCE
    ]
    return random.choice(within_tolerance)


def select_tasks_for_task_score(
    tasks: List[Dict],
    task_score: float,
    mode_preference: int,
    count: int,
    assigned_task_ids: Optional[List[str]] = None,
    exclude_recent_ids: Optional[List[str]] = None,
) -> List[Dict]:
    """
    mode_preference 0 = guide me -> return 1 task (auto).
    mode_preference 1 = I'll choose -> return up to `count` options (anti-repeat by exclude_recent_ids).
    assigned_task_ids: if set and mode=choose, prefer these (filter by score band).
    """
    active = [t for t in tasks if t.get("is_active") is True]
    matching = []
    for t in active:
        mn = float(t.get("min_task_score", 0))
        mx = float(t.get("max_task_score", 1))
        if mn <= task_score <= mx:
            matching.append(t)
    exclude = set(exclude_recent_ids or [])
    if exclude:
        matching = [t for t in matching if str(t.get("id")) not in exclude]
    if not matching:
        return []

    if mode_preference == 0:
        # Guide me: return 1 (first matching, or first assigned)
        if assigned_task_ids:
            for tid in assigned_task_ids:
                for t in matching:
                    if str(t.get("id")) == str(tid):
                        return [t]
        return [matching[0]]

    # I'll choose: return up to `count` options (prefer assigned first)
    out = []
    if assigned_task_ids:
        for tid in assigned_task_ids:
            if len(out) >= count:
                break
            for t in matching:
                if str(t.get("id")) == str(tid) and t not in out:
                    out.append(t)
                    break
    for t in matching:
        if len(out) >= count:
            break
        if t not in out:
            out.append(t)
    return out[:count]
