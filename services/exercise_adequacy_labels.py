"""The scorekeeper: did the exercise help? (step 8 prep; §3.5 item 1).

Turns each exposure the counter counts into one label under
exercise-adequacy-label-v1 (founder 2026-09-28,
docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5):

  * **helped** when none of the exposure's targeted problems fires on its
    endpoint attempt (item 1);
  * the targeted problems come from the frozen match trace (0384), never
    recomputed;
  * the endpoint attempt is measured by the same detector rules
    (`clip_signals`, under the SIGNAL_RULES_VERSION the trace was written
    under) and filtered by the library vocabulary frozen in that trace;
  * the endpoint is the last valid attempt, never the best (item 3);
  * missing attempts are never labels (item 5) — the counter already left
    them out, and this reads the counter's own cohort (`cohort_records`), so
    the two can never disagree about which exposures count.

SEALED UNTIL THE BAR IS MET. `labels()` returns nothing but "sealed" and the
counter's reason until the evidence bar (item 8) is reached. Looking at
success rates while the data fills would let someone stop early on a lucky
streak; the seal makes that impossible through this module. `build_labels`
stays pure so tests and the fair-test calculator can run it on fixtures.

Never a label here (item 10): the speaker's answers, coach or peer
judgments, coach overrides, shadow verdicts, "shown" or "opened". Nothing
reads them. Internal only: no route serves this, and nothing reaches a
speaker or a coach.
"""
from __future__ import annotations

from typing import Any

from services.exercise_learning_readiness import (
    LABEL_SPEC_VERSION,
    cohort_records,
    read_sources,
    readiness,
    targeted_problems,
)

SCOREKEEPER_VERSION = "exercise-adequacy-scorekeeper-v1"


def endpoint_problems(attempt: Any, trace: Any) -> frozenset[str]:
    """The library problems that fire on an endpoint attempt, by the same
    rules as the original clip and the vocabulary frozen in its trace."""
    from services.confident_voice_practice import (
        clip_signals,
        observed_problem_tags,
    )
    snap = (attempt or {}).get("acoustic_metrics") if isinstance(attempt, dict) \
        else None
    if not isinstance(snap, dict):
        return frozenset()
    vocabulary = (trace or {}).get("vocabulary") if isinstance(trace, dict) \
        else None
    return observed_problem_tags({"signals": clip_signals(snap)},
                                 vocabulary=vocabulary or None)


def label(record: dict) -> dict:
    """One counted exposure's label."""
    exposure, trace = record["exposure"], record["trace"]
    endpoint = record["endpoint"]
    exercise_id = str(exposure.get("exercise_id") or "")
    targets = targeted_problems(trace, exercise_id)
    still = targets & endpoint_problems(endpoint, trace)
    return {
        "label_spec_version": LABEL_SPEC_VERSION,
        "scorekeeper_version": SCOREKEEPER_VERSION,
        "signal_rules_version": trace.get("signal_rules_version"),
        "assignment_id": str(exposure.get("assignment_id") or ""),
        "owner_user_id": str(exposure.get("owner_user_id") or ""),
        "exercise_id": exercise_id,
        "exercise_version": exposure.get("exercise_version"),
        "fit": trace.get("fit"),
        "selection_mode": record["assignment"].get("selection_mode"),
        "targeted_problems": sorted(targets),
        "still_firing": sorted(still),
        "endpoint_attempt_index": endpoint.get("attempt_index"),
        "helped": not still,
    }


def build_labels(*, signal_rules_version: str, **rows: Any) -> list[dict]:
    """A label for every exposure the counter counts, in render order. Pure;
    unsealed — only fixtures and the fair-test calculator call it directly."""
    return [label(r) for r in cohort_records(
        signal_rules_version=signal_rules_version, **rows)
        if r["excluded"] is None]


def labels(database: Any) -> dict:
    """The labels once the evidence bar is met; until then only why not."""
    from services.confident_voice_practice import SIGNAL_RULES_VERSION
    gate = readiness(database)
    if not gate.get("ready"):
        return {"sealed": True, "why_not": gate.get("why_not"),
                "label_spec_version": LABEL_SPEC_VERSION}
    rows, unavailable = read_sources(database)
    if unavailable:
        return {"sealed": True,
                "why_not": "unreadable: " + ", ".join(unavailable),
                "label_spec_version": LABEL_SPEC_VERSION}
    return {"sealed": False, "label_spec_version": LABEL_SPEC_VERSION,
            "labels": build_labels(signal_rules_version=SIGNAL_RULES_VERSION,
                                   **rows)}
