"""
V2 flow: task_score, exercise/task/post-question selection.
No themes in v1; selection is by task_score and mode_preference.
"""
import logging
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


# Recurring issue -> task target names for weakness-match scoring (Step 4)
RECURRING_ISSUE_TARGETS = {
    "too_fast": ["pacing"],
    "too_slow": ["pacing"],
    "high_fillers": ["fillers"],
}
WEAKNESS_MATCH_BONUS = 2.0


def score_and_pick_focus_task(
    candidates: List[Dict],
    recurring_issues: List[str],
    performance_score_1: float,
) -> Optional[Dict]:
    """
    Multi-factor pick: choose task that best matches recurring_issues (weakness match).
    candidates: eligible tasks (already filtered by score band and novelty).
    recurring_issues: e.g. ["too_fast", "high_fillers"] from coaching memory.
    Returns the best task dict (id, text, ...) or None if candidates empty.
    Tie-break: first in list (preserves order_index preference).
    """
    if not candidates:
        return None
    wanted_targets = set()
    for issue in (recurring_issues or []):
        if not isinstance(issue, str) or not issue.strip():
            continue
        for t in RECURRING_ISSUE_TARGETS.get(issue.strip(), []):
            wanted_targets.add(t)
    if not wanted_targets:
        return candidates[0]

    best_task = None
    best_score = -1.0
    # Temporary: remove after validation. Log scoring breakdown for baseline testing.
    _log = []
    for task in candidates:
        score = 0.0
        targets = task.get("targets")
        if isinstance(targets, list):
            task_targets = {str(x).strip().lower() for x in targets if x}
            for w in wanted_targets:
                if w.lower() in task_targets:
                    score += WEAKNESS_MATCH_BONUS
                    break
        _log.append({
            "task_id": task.get("id"),
            "weakness_score": score,
            "total_score": score,
        })
        if score > best_score:
            best_score = score
            best_task = task
    chosen = best_task if best_task is not None else candidates[0]
    if _log and logging.getLogger().isEnabledFor(logging.DEBUG):
        for entry in _log:
            entry["chosen"] = chosen and str(chosen.get("id")) == str(entry.get("task_id"))
        logging.debug("FOCUS_TASK_SCORING %s", _log)
    return chosen


def select_focus_task_for_performance_score_1(
    tasks: List[Dict],
    performance_score_1: float,
    assigned_task_ids: Optional[List[str]] = None,
) -> Optional[Dict]:
    """
    Homework flow: pick one focus task where min_task_score <= performance_score_1.
    If assigned_task_ids is set, only consider those tasks; else consider all active.
    If several match, shuffle and return one.
    If no task is eligible (score_1 below all min_task_scores), pick easiest so flow never blocks:
    easiest = task with smallest min_task_score.
    """
    import random
    active = [t for t in tasks if t.get("is_active") is True]
    if not active:
        return None
    if assigned_task_ids:
        allowed = {str(tid) for tid in assigned_task_ids}
        active = [t for t in active if str(t.get("id")) in allowed]
    if not active:
        return None
    matching = []
    for t in active:
        mn = float(t.get("min_task_score", 0))
        if mn <= performance_score_1:
            matching.append(t)
    if matching:
        random.shuffle(matching)
        return matching[0]
    # No eligible task: pick easiest (smallest min_task_score) so flow never blocks
    easiest = min(active, key=lambda t: float(t.get("min_task_score", 0)))
    return easiest


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
