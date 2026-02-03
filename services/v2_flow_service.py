"""
V2 flow: task_score, exercise/task/post-question selection.
No themes in v1; selection is by task_score and mode_preference.
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


def select_exercise_for_task_score(
    exercises: List[Dict],
    task_score: float,
    assigned_exercise_id: Optional[str] = None,
) -> Optional[Dict]:
    """
    If assigned_exercise_id is set, return that exercise if active.
    Else pick one exercise where min_task_score <= task_score <= max_task_score.
    If no active exercises, return None (skip step).
    """
    active = [e for e in exercises if e.get("is_active") is True]
    if not active:
        return None
    if assigned_exercise_id:
        for e in active:
            if str(e.get("id")) == str(assigned_exercise_id):
                return e
    # Pick first matching by score band
    for e in active:
        mn = float(e.get("min_task_score", 0))
        mx = float(e.get("max_task_score", 1))
        if mn <= task_score <= mx:
            return e
    return None


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


def select_post_questions_v2(
    pool: List[Dict],
    assigned_ids: Optional[List[str]] = None,
    must_include_code: str = "emotion_achieved_check",
) -> List[Dict]:
    """
    Return exactly 3 questions. Must include one with code=emotion_achieved_check.
    If assigned_ids has exactly 3, use those (and ensure one is emotion_achieved_check).
    Else pick 3 active, ensuring one has code=emotion_achieved_check.
    """
    active = [q for q in pool if q.get("is_active") is True]
    emotion_q = next((q for q in active if q.get("code") == must_include_code), None)
    if not emotion_q:
        # Must have at least the emotion question in pool
        return []

    if assigned_ids and len(assigned_ids) == 3:
        ordered = []
        for aid in assigned_ids:
            for q in active:
                if str(q.get("id")) == str(aid):
                    ordered.append(q)
                    break
        if len(ordered) == 3 and any(q.get("code") == must_include_code for q in ordered):
            return ordered
        # Fall through to default pick

    # Build set of 3: emotion_q + 2 others
    others = [q for q in active if q.get("id") != emotion_q.get("id")]
    if len(others) < 2:
        return [emotion_q] + others  # may be 1 or 2 total
    return [emotion_q, others[0], others[1]]
