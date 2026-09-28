"""Which patterns get spotted, and which exercises cover them (step 5).

The CMS gap view (founder 2026-09-28). It answers the coach's working
question — "which exercise should I film next?" — from what actually
happened on Takes, not from what anyone remembers:

  * spotted: how often each detected pattern fired on a Take's exercise
    moment in the window. Read from the frozen records of those moments:
    every match trace (0384) and every coach request (0385) carries the
    patterns that fired on that exact clip, so nothing is recomputed;
  * coverage: which active exercises target it as their main target, and
    which only as a secondary one (a trial, D5);
  * open coach requests that name it — moments waiting on a coach because no
    exercise targets what was spotted;
  * shadow patterns (D3): how many clips their detector measured and fired on.
    They route nothing yet, so they have no "spotted" moments; this is what
    tells the coach an exercise will be needed if the pattern is promoted.

Internal only: an admin CMS surface. Nothing here reaches a speaker, and a
count here is never a judgment about any person.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_DAYS = 30
MAX_DAYS = 90


def window_days(value: Any) -> int:
    """The window in days, clamped to 1..MAX_DAYS; DEFAULT_DAYS when absent
    or not a whole number."""
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_DAYS
    return max(1, min(MAX_DAYS, value))


def build_gap_view(*, library: list[dict], exercises: list[dict],
                   spotted_tags: list[list[str]], requests: list[dict],
                   shadow: dict[str, dict], days: int) -> dict:
    """The view from already-read rows. Pure."""
    from services.confident_voice_practice import exercise_targets

    spotted: dict[str, int] = {}
    for tags in spotted_tags:
        for tag in set(tags or ()):
            spotted[str(tag)] = spotted.get(str(tag), 0) + 1

    open_requests: dict[str, int] = {}
    nothing_spotted_open = 0
    for request in requests:
        if not isinstance(request, dict) or request.get("resolution"):
            continue
        if request.get("reason") == "nothing_spotted":
            nothing_spotted_open += 1
        for tag in set(request.get("observed_tags") or ()):
            open_requests[str(tag)] = open_requests.get(str(tag), 0) + 1

    main_of: dict[str, list[str]] = {}
    secondary_of: dict[str, list[str]] = {}
    for exercise in exercises:
        exercise_id = str(exercise.get("exercise_id") or "")
        main, secondary = exercise_targets(exercise)
        for tag in main:
            main_of.setdefault(tag, []).append(exercise_id)
        for tag in secondary:
            secondary_of.setdefault(tag, []).append(exercise_id)

    rows: list[dict[str, Any]] = []
    for entry in library:
        if not isinstance(entry, dict) or entry.get("active") is False:
            continue
        error_id = str(entry.get("error_id") or "")
        status = entry.get("status")
        main_ids = sorted(main_of.get(error_id, []))
        secondary_ids = sorted(secondary_of.get(error_id, []))
        if status == "shadow":
            coverage = "being_tested"
        elif status != "detected":
            coverage = "not_detectable_yet"
        elif main_ids:
            coverage = "covered"
        elif secondary_ids:
            coverage = "trial_only"
        else:
            coverage = "no_exercise"
        row = {
            "error_id": error_id,
            "label": entry.get("label") or error_id,
            "status": status,
            "coverage": coverage,
            "spotted": spotted.get(error_id, 0),
            "open_coach_requests": open_requests.get(error_id, 0),
            "main_exercises": main_ids,
            "secondary_exercises": secondary_ids,
        }
        if status == "shadow":
            row["shadow"] = shadow.get(error_id) or {
                "clips_measured": 0, "clips_fired": 0}
        rows.append(row)

    # The ones to film next first: detected, spotted, and nothing treats them
    # as a main target. Then by how often they were spotted.
    urgency = {"no_exercise": 0, "trial_only": 1, "covered": 2,
               "being_tested": 3, "not_detectable_yet": 4}
    rows.sort(key=lambda r: (urgency[str(r["coverage"])], -int(r["spotted"]),
                             -int(r["open_coach_requests"]),
                             str(r["error_id"])))
    return {"days": days, "patterns": rows,
            "nothing_spotted_open_requests": nothing_spotted_open}


def gap_view(database: Any, *, days: Any = None) -> dict:
    """Read everything the view needs and build it. A source that cannot be
    read (a migration not yet applied) is named in `unavailable` rather than
    read as zero."""
    from services.confident_voice_practice import offerable_exercises
    window = window_days(days)
    since = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
    unavailable: list[str] = []

    def read(name: str, fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001 — named below, never read as zero
            unavailable.append(name)
            return default

    library = database.list_speaking_errors(active_only=False) or []
    view = build_gap_view(
        library=library,
        exercises=offerable_exercises(database),
        spotted_tags=read("match_traces",
                          lambda: database.list_match_trace_tags(since), []),
        requests=read("coach_requests",
                      lambda: database.list_exercise_coach_requests(since), []),
        shadow=read("shadow_observations", lambda: {
            str(e["error_id"]): database.count_verbal_cue_shadow(
                str(e["error_id"]), since)
            for e in library
            if isinstance(e, dict) and e.get("status") == "shadow"}, {}),
        days=window)
    view["unavailable"] = unavailable
    return view
