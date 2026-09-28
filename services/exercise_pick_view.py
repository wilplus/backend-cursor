"""What the machine picked and why, for the coach AFTER their blind rating.

Step 6 of the exercise routing plan (founder 2026-09-28; contract 35f). The
match trace (0384) and the coach request (0385) already freeze why a moment
got its exercise — or none. This turns them into what a coach can use once
their own confidence judgment is saved: which problems were spotted, whether
the exercise was an exact fit or a trial, whether it was the best match or
the 80/20 "try something new" pick, and what happened to every other
exercise in the library.

WHAT IS NEVER SHOWN, EVEN NOW. A trace also holds the clip's measurements and
the machine's confidence read of it (`features`, `pattern`, `gate`). Those
stay out: the confidence read is exactly the machine guess the BLIND COACH
fence keeps from a rater, and the raw measurements add nothing a coach acts
on. What is shown is routing — problems, fits, reasons — never a verdict on
how confident the speaker sounded.

The callers are coach-only payloads reached through the blind gate. Nothing
here reaches a speaker.
"""
from __future__ import annotations

from typing import Any, Optional

#: How the 80/20 draw chose (migration 0372), in words a coach reads.
HOW_CHOSEN = {
    "top": "best_match",
    "exploration": "trying_another",
    "deterministic_singleton": "only_match",
}


def _labels(database: Any) -> dict:
    rows = (database.list_speaking_errors() or []
            if hasattr(database, "list_speaking_errors") else [])
    return {str(r.get("error_id")): r.get("label")
            for r in rows if isinstance(r, dict) and r.get("error_id")}


def _named(tags: Any, labels: dict) -> list[dict]:
    return [{"error_id": str(tag), "label": labels.get(str(tag)) or str(tag)}
            for tag in (tags or [])]


def candidates_view(trace: Any) -> list[dict]:
    """Every exercise the moment was matched against: ranked ones in rank
    order, then the excluded ones with why. Routing fields only."""
    rows = trace.get("candidates") if isinstance(trace, dict) else None
    if not isinstance(rows, list):
        return []
    out = [{
        "exercise_id": row.get("exercise_id"),
        "outcome": row.get("outcome"),
        "reason": row.get("reason"),
        "rank": row.get("rank"),
        "fit": row.get("fit"),
        "main_targets": row.get("main_targets") or [],
        "secondary_targets": row.get("secondary_targets") or [],
    } for row in rows if isinstance(row, dict)]
    return sorted(out, key=lambda r: (r["outcome"] != "ranked",
                                      r["rank"] or 0, str(r["exercise_id"])))


def machine_pick(database: Any, take_session_id: Any,
                 snippet_id: Any) -> Optional[dict]:
    """The machine's frozen pick for one moment, or None when the moment
    had no draw (nothing fitted, a coach-shared exercise, or before 0372)."""
    get_assignment = getattr(
        database, "get_confident_voice_exercise_assignment", None)
    assignment = (get_assignment(str(take_session_id), str(snippet_id))
                  if get_assignment is not None else None)
    if not isinstance(assignment, dict):
        return None
    get_trace = getattr(database, "get_exercise_match_trace", None)
    trace_row = (get_trace(str(assignment.get("id") or ""))
                 if get_trace is not None else None)
    trace = (trace_row.get("trace")
             if isinstance(trace_row, dict) else None)
    from services.confident_voice_practice import fit_from_policy
    return {
        "exercise_id": assignment.get("selected_exercise_id"),
        "version": assignment.get("selected_exercise_version"),
        "fit": fit_from_policy(assignment.get("matching_policy_version")),
        "how_chosen": HOW_CHOSEN.get(str(assignment.get("selection_mode"))),
        # Drawn before traces existed (0384): the pick is known, the why
        # is not, and the payload says so rather than inventing one.
        "traced": isinstance(trace, dict),
        "spotted": _named(trace.get("observed_tags")
                          if isinstance(trace, dict) else [],
                          _labels(database)),
        "candidates": candidates_view(trace),
        "rules_version": (trace.get("signal_rules_version")
                          if isinstance(trace, dict) else None),
    }


def request_candidates(request: Any) -> list[dict]:
    """Why nothing fitted a coach-request moment: every exercise and its
    reason, from the request's own frozen trace."""
    trace = request.get("request_trace") if isinstance(request, dict) else None
    return candidates_view(trace)
