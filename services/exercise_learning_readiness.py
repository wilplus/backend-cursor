"""How close the exercise-adequacy data is to its evidence bar (step 8 prep).

The learning contract (exercise-adequacy-label-v1, founder 2026-09-28,
docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5) says no learned ranking may even
be evaluated before at least 300 first-exposure attempts with a valid
endpoint, and 30 for every exercise it would rank (item 8). This counts them,
so the founder can watch the jar fill instead of guessing.

IT COUNTS; IT NEVER LOOKS AT OUTCOMES. Nothing here reads whether a problem
stopped firing. Peeking at success rates while the data fills would let the
bar be judged against the result it is meant to protect, so this module does
not compute the endpoint at all — the scorekeeper, a separate later step,
does.

The funnel follows §3.5 item by item:

  * an exposure exists only once the client confirmed it rendered (item 5,
    migration 0387);
  * its targeted problems are read from the frozen match trace (0384): the
    problems that fired on the clip and that the served exercise targets at
    its fit — main target for exact, secondary for a trial (item 1). An
    exposure drawn before traces existed has no targets and is left out;
  * a trace written under other signal rules is left out, not compared
    (item 1);
  * only a speaker's first exposure per targeted problem enters the cohort;
    repeats are counted separately (item 6). The reading here is strict: an
    exposure is first only when none of its targeted problems was targeted
    for that speaker before;
  * an exposure below the policy's minimum probability is left out (item 6);
  * the endpoint attempt is the last valid attempt in the practice flow the
    speaker opened on that assignment (items 2 and 3). No attempt, or none
    valid, is missing data, never a negative (item 5); the attempt rate is
    reported beside the count.

Internal only: an admin CMS surface. No number here reaches a speaker or a
coach, and a count here is never a judgment about any person.
"""
from __future__ import annotations

from typing import Any, Optional

LABEL_SPEC_VERSION = "exercise-adequacy-label-v1"
READINESS_VERSION = "exercise-learning-readiness-v1"

#: §3.5 item 8 (founder 2026-09-28). Changing either is the founder's call.
MIN_COUNTED = 300
MIN_PER_EXERCISE = 30

#: Why an exposure is not counted, in the order the checks run.
EXCLUSIONS = ("untraced", "no_targeted_problem", "rules_changed", "repeat",
              "below_minimum_probability", "no_attempt", "no_valid_attempt")


def targeted_problems(trace: Any, exercise_id: str) -> frozenset[str]:
    """The problems this exposure is judged on (§3.5 item 1), from the trace."""
    if not isinstance(trace, dict):
        return frozenset()
    observed = {str(t) for t in trace.get("observed_tags") or ()}
    targets_key = "secondary_targets" if trace.get("fit") == "trial" \
        else "main_targets"
    for row in trace.get("candidates") or ():
        if isinstance(row, dict) and str(row.get("exercise_id")) == exercise_id:
            return frozenset(observed & {str(t) for t in
                                         row.get(targets_key) or ()})
    return frozenset()


def ranked_pool(trace: Any) -> list[str]:
    """The exercises the draw chose between: the ones a ranker would rank."""
    if not isinstance(trace, dict):
        return []
    return [str(row.get("exercise_id")) for row in trace.get("candidates") or ()
            if isinstance(row, dict) and row.get("outcome") == "ranked"]


def attempt_is_valid(attempt: Any) -> bool:
    """The safety half of the clip gate, on a saved practice attempt (§3.5
    item 3). A saved attempt already passed the exact-passage check; the
    reliability and confidence halves are the same rules the original clip
    met (`_audio_reliable`, and a confidence read present), including the
    noise rule once it is switched on (NOISE_GATE_MIN_SEPARATION_DB)."""
    from services.confident_voice_practice import _audio_reliable
    if not isinstance(attempt, dict):
        return False
    snap = attempt.get("acoustic_metrics")
    if not isinstance(snap, dict):
        return False
    if int(snap.get("aligned_words") or 0) < 4:
        return False
    confidence = snap.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    return _audio_reliable({"duration_ms": attempt.get("duration_ms"),
                            "audio_ref": attempt.get("audio_ref")
                                         or attempt.get("storage_path")},
                           snap)


def endpoint_attempt(attempts: list[dict]) -> Optional[dict]:
    """The last valid attempt of at most three (§3.5 item 3); never the best."""
    ordered = sorted((a for a in attempts if isinstance(a, dict)),
                     key=lambda a: int(a.get("attempt_index") or 0))[:3]
    valid = [a for a in ordered if attempt_is_valid(a)]
    return valid[-1] if valid else None


def _gate(exposure: dict, *, trace: Any, assignment: dict,
          seen: dict[str, set[str]], signal_rules_version: str) -> Optional[str]:
    """The first rule-gate an exposure fails before the cohort, or None.
    Marks its targeted problems as seen for the speaker either way."""
    if not isinstance(trace, dict):
        return "untraced"
    targets = targeted_problems(trace, str(exposure.get("exercise_id") or ""))
    if not targets:
        return "no_targeted_problem"
    earlier = seen.setdefault(str(exposure.get("owner_user_id") or ""), set())
    first = not (targets & earlier)
    earlier.update(targets)
    if trace.get("signal_rules_version") != signal_rules_version:
        return "rules_changed"
    if not first:
        return "repeat"
    if assignment.get("below_minimum_probability"):
        return "below_minimum_probability"
    return None


def _noise_gate_version() -> str:
    from services.confident_voice_practice import noise_gate_version
    return noise_gate_version()


def _why_not(counted: int, rows: list[dict], pool: set[str]) -> Optional[str]:
    short = [r["exercise_id"] for r in rows
             if r["exercise_id"] in pool and int(r["counted"]) < MIN_PER_EXERCISE]
    if counted < MIN_COUNTED:
        return (f"{counted} of {MIN_COUNTED} first-exposure attempts with a "
                "valid endpoint")
    if short:
        return (f"{len(short)} exercise(s) below {MIN_PER_EXERCISE}: "
                + ", ".join(short))
    return None


def cohort_records(*, exposures: list[dict], assignments: dict[str, dict],
                   traces: dict[str, dict], practices: dict[str, dict],
                   attempts: dict[str, list[dict]],
                   signal_rules_version: str) -> list[dict]:
    """Every confirmed render, in render order, with where §3.5 put it. Pure.

    Each record is `{exposure, assignment, trace, in_cohort, excluded,
    endpoint}`: `excluded` names the first gate it failed (None when it
    counts) and `endpoint` is its endpoint attempt when it counts. The
    counter and the scorekeeper both read this, so they can never disagree
    about which exposures count.

    `assignments` and `traces` are keyed by assignment id; `practices` maps an
    assignment id to the first practice the speaker opened on it; `attempts`
    maps a practice id to its attempts.
    """
    seen: dict[str, set[str]] = {}
    records: list[dict] = []
    ordered = sorted((e for e in exposures if isinstance(e, dict)),
                     key=lambda e: (str(e.get("rendered_at") or ""),
                                    str(e.get("assignment_id") or "")))
    for exposure in ordered:
        assignment_id = str(exposure.get("assignment_id") or "")
        assignment = assignments.get(assignment_id) or {}
        trace = traces.get(assignment_id)
        refused = _gate(exposure, trace=trace, assignment=assignment,
                        seen=seen, signal_rules_version=signal_rules_version)
        in_cohort = refused is None
        endpoint = None
        if in_cohort:
            practice = practices.get(assignment_id) or {}
            tries = attempts.get(str(practice.get("id") or ""), [])
            endpoint = endpoint_attempt(tries) if tries else None
            refused = ("no_attempt" if not tries else
                       "no_valid_attempt" if endpoint is None else None)
        records.append({"exposure": exposure, "assignment": assignment,
                        "trace": trace, "in_cohort": in_cohort,
                        "excluded": refused, "endpoint": endpoint})
    return records


def build_readiness(*, signal_rules_version: str, **rows: Any) -> dict:
    """The count from already-read rows (see `cohort_records`). Pure."""
    excluded = {name: 0 for name in EXCLUSIONS}
    per_exercise: dict[str, dict[str, Any]] = {}
    pool: set[str] = set()
    modes: dict[str, int] = {}
    cohort = counted = 0

    def slot(exercise_id: str) -> dict[str, Any]:
        return per_exercise.setdefault(exercise_id, {
            "exercise_id": exercise_id, "exposures": 0, "cohort": 0,
            "counted": 0, "needed": MIN_PER_EXERCISE})

    records = cohort_records(signal_rules_version=signal_rules_version, **rows)
    for record in records:
        row = slot(str(record["exposure"].get("exercise_id") or ""))
        row["exposures"] += 1
        if record["in_cohort"]:
            cohort += 1
            row["cohort"] += 1
            pool.update(ranked_pool(record["trace"]))
        if record["excluded"] is not None:
            excluded[record["excluded"]] += 1
            continue
        counted += 1
        row["counted"] += 1
        mode = str(record["assignment"].get("selection_mode") or "unknown")
        modes[mode] = modes.get(mode, 0) + 1

    for exercise_id in pool:
        slot(exercise_id)
    table = sorted(per_exercise.values(),
                   key=lambda r: (int(r["counted"]), str(r["exercise_id"])))
    why_not = _why_not(counted, table, pool)
    return {
        "label_spec_version": LABEL_SPEC_VERSION,
        "readiness_version": READINESS_VERSION,
        "signal_rules_version": signal_rules_version,
        "noise_gate_version": _noise_gate_version(),
        "bar": {"min_counted": MIN_COUNTED,
                "min_per_exercise": MIN_PER_EXERCISE},
        "exposures": len(records),
        "cohort": cohort,
        "counted": counted,
        "attempt_rate": round(counted / cohort, 4) if cohort else None,
        "excluded": excluded,
        "counted_by_selection_mode": modes,
        "exercises": table,
        "ready": why_not is None,
        "why_not": why_not,
    }


def read_sources(database: Any) -> tuple[dict, list[str]]:
    """The rows `cohort_records` needs, and the names of any source that
    could not be read (a migration not yet applied)."""
    unavailable: list[str] = []

    def read(name: str, fn: Any, default: Any) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001 — named, never read as zero
            unavailable.append(name)
            return default

    exposures = read("exposures", database.list_exercise_exposures, [])
    ids = sorted({str(e.get("assignment_id")) for e in exposures
                  if isinstance(e, dict) and e.get("assignment_id")})
    assignments = read("assignments",
                       lambda: database.get_exercise_assignments(ids), {})
    traces = read("match_traces",
                  lambda: database.get_exercise_match_traces(ids), {})
    practices = read("practices",
                     lambda: database.get_practices_for_assignments(ids), {})
    practice_ids = sorted({str(p.get("id")) for p in practices.values()
                           if isinstance(p, dict) and p.get("id")})
    attempts = read("attempts",
                    lambda: database.list_attempts_for_practices(practice_ids),
                    {})
    return ({"exposures": exposures, "assignments": assignments,
             "traces": traces, "practices": practices, "attempts": attempts},
            unavailable)


def readiness(database: Any) -> dict:
    """Read everything the count needs and build it. A source that cannot be
    read is named in `unavailable`; the count is then marked not ready rather
    than read as smaller."""
    from services.confident_voice_practice import SIGNAL_RULES_VERSION
    rows, unavailable = read_sources(database)
    out = build_readiness(signal_rules_version=SIGNAL_RULES_VERSION, **rows)
    out["unavailable"] = unavailable
    if unavailable:
        out["ready"] = False
        out["why_not"] = "unreadable: " + ", ".join(unavailable)
    return out
