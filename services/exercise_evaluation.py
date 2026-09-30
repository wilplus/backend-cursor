"""The full jar unseals the evaluation (founder 2026-09-29, evening: "a
full jar unlocks by itself", option 1; coach picks in, in their own pile).

Until now the scorekeeper (services/exercise_adequacy_labels) and the fair
test (services/exercise_fair_test) answered only "sealed" and no route
served them. The founder's decision: when the counter says the bar is met
(300 first-exposure attempts with a valid endpoint, 30 per exercise, §3.5
item 8) the evaluation runs on its own and its result is shown on the jar
page. That is the whole of what unseals. NOTHING PROMOTES: a learned
ranking still only ever reorders the already-safe pool, only after a
founder's yes, and no code path here or anywhere serves one. Below the bar
this module answers exactly what the counter answers: sealed, and why.

TWO PILES, NEVER MIXED (L3). A coach's pick (0398, selection mode
``coach_chosen``) counts in the jar under its own label, so the evaluation
is built twice: ``machine_only`` from machine draws, ``with_coach_picks``
from both. The fair test's graded units are machine draws in both piles (a
coach pick has no logged odds, so no policy can be compared on it); what
differs between the piles is what the candidate learns from, and the
scoreboard.

THE CANDIDATE. A fair test needs a ranker to grade. The first one is the
simplest honest one: within the moment's own eligible pool, prefer the
exercise with the highest helped rate on study-group ("train") speakers,
requiring the per-exercise bar of labels before trusting a rate, ties and
unknowns falling back to today's fixed ranking. It is graded on exam-group
("holdout") speakers only, as the fair test always does. Its name is
``exercise-success-ranked-v1``. It is a proposal to look at, not a policy.

Internal only: the founder's CMS jar page. No number here reaches a
speaker or a coach, and a rate here is about an exercise, never a person.
"""
from __future__ import annotations

from typing import Any, Optional

from services.exercise_adequacy_labels import SCOREKEEPER_VERSION, label
from services.exercise_fair_test import (
    FAIR_TEST_VERSION,
    Choose,
    compare,
    fixed_ranking,
    split_of,
    units_from,
)
from services.exercise_learning_readiness import (
    LABEL_SPEC_VERSION,
    MIN_COUNTED,
    MIN_PER_EXERCISE,
    cohort_records,
    read_sources,
    readiness,
)

EVALUATION_VERSION = "exercise-jar-evaluation-v1"
CANDIDATE_VERSION = "exercise-success-ranked-v1"
COACH_MODE = "coach_chosen"
PILES = ("machine_only", "with_coach_picks")


def _rate(helped: int, counted: int) -> Optional[float]:
    return round(helped / counted, 4) if counted else None


def scoreboard(labels: list[dict]) -> dict:
    """The scorekeeper's labels, added up: overall, per exercise, and per
    selection mode. Pure. A rate is about an exercise, never a person."""
    per: dict[str, dict[str, int]] = {}
    modes: dict[str, dict[str, int]] = {}
    helped_total = 0
    for row in labels:
        helped = bool(row.get("helped"))
        helped_total += helped
        slot = per.setdefault(str(row.get("exercise_id") or ""),
                              {"counted": 0, "helped": 0})
        slot["counted"] += 1
        slot["helped"] += helped
        mode = modes.setdefault(str(row.get("selection_mode") or "unknown"),
                                {"counted": 0, "helped": 0})
        mode["counted"] += 1
        mode["helped"] += helped
    return {
        "counted": len(labels),
        "helped": helped_total,
        "helped_rate": _rate(helped_total, len(labels)),
        "exercises": [
            {"exercise_id": exercise_id, **counts,
             "helped_rate": _rate(counts["helped"], counts["counted"])}
            for exercise_id, counts in sorted(per.items())],
        "by_selection_mode": {
            mode: {**counts, "helped_rate": _rate(counts["helped"], counts["counted"])}
            for mode, counts in sorted(modes.items())},
    }


def train_rates(labels: list[dict]) -> dict[str, tuple[int, int]]:
    """(helped, counted) per exercise on study-group speakers only. Pure."""
    out: dict[str, list[int]] = {}
    for row in labels:
        if split_of(str(row.get("owner_user_id") or "")) != "train":
            continue
        slot = out.setdefault(str(row.get("exercise_id") or ""), [0, 0])
        slot[0] += bool(row.get("helped"))
        slot[1] += 1
    return {exercise_id: (h, n) for exercise_id, (h, n) in out.items()}


def success_ranked(rates: dict[str, tuple[int, int]],
                   min_counted: int = MIN_PER_EXERCISE) -> Choose:
    """The candidate: within the unit's own pool, the exercise with the
    highest study-group helped rate among those with at least
    ``min_counted`` labels; otherwise today's fixed ranking."""
    def choose(unit: dict) -> Optional[str]:
        best: Optional[str] = None
        best_rate = -1.0
        for exercise_id in unit.get("pool") or ():
            helped, counted = rates.get(str(exercise_id), (0, 0))
            if counted < min_counted:
                continue
            rate = helped / counted
            if rate > best_rate:
                best, best_rate = str(exercise_id), rate
        return best if best is not None else fixed_ranking(unit)
    return choose


def _preferences(rates: dict[str, tuple[int, int]],
                 min_counted: int = MIN_PER_EXERCISE) -> list[dict]:
    """What the candidate learned, readable: the rates it would rank by."""
    return [
        {"exercise_id": exercise_id, "helped": h, "counted": n,
         "helped_rate": _rate(h, n), "trusted": n >= min_counted}
        for exercise_id, (h, n) in sorted(rates.items())]


def _pile(labels: list[dict], units: list[dict]) -> dict:
    rates = train_rates(labels)
    return {
        "scoreboard": scoreboard(labels),
        "candidate": {
            "version": CANDIDATE_VERSION,
            "learned_from": {
                "labels": sum(1 for row in labels
                              if split_of(str(row.get("owner_user_id") or "")) == "train"),
                "speakers": len({str(row.get("owner_user_id") or "") for row in labels
                                 if split_of(str(row.get("owner_user_id") or "")) == "train"}),
            },
            "preferences": _preferences(rates),
        },
        "fair_test": compare(units, success_ranked(rates)),
    }


def build_evaluation(records: list[dict]) -> dict:
    """Both piles from the counter's own records (see ``cohort_records``).
    Pure; unsealed, for fixtures and ``evaluate_jar``."""
    labels = [label(r) for r in records if r["excluded"] is None]
    units = units_from(records)
    machine = [row for row in labels if row.get("selection_mode") != COACH_MODE]
    return {
        "machine_only": _pile(machine, units),
        "with_coach_picks": _pile(labels, units),
        "coach_pick_labels": len(labels) - len(machine),
    }


def evaluate_jar(database: Any, gate: Optional[dict] = None) -> dict:
    """The evaluation once the bar is met; until then sealed, and why.

    ``gate`` is the counter's report when the caller already has it.
    """
    from services.confident_voice_practice import SIGNAL_RULES_VERSION
    head = {
        "evaluation_version": EVALUATION_VERSION,
        "label_spec_version": LABEL_SPEC_VERSION,
        "scorekeeper_version": SCOREKEEPER_VERSION,
        "fair_test_version": FAIR_TEST_VERSION,
        "candidate_version": CANDIDATE_VERSION,
        "bar": {"min_counted": MIN_COUNTED, "min_per_exercise": MIN_PER_EXERCISE},
        "requires_founder_approval": True,
        "promotes": False,
    }
    gate = gate if isinstance(gate, dict) else readiness(database)
    if not gate.get("ready"):
        return {**head, "sealed": True, "why_not": gate.get("why_not")}
    rows, unavailable = read_sources(database)
    if unavailable:
        return {**head, "sealed": True,
                "why_not": "unreadable: " + ", ".join(unavailable)}
    records = cohort_records(signal_rules_version=SIGNAL_RULES_VERSION, **rows)
    return {**head, "sealed": False, "why_not": None,
            "signal_rules_version": SIGNAL_RULES_VERSION,
            **build_evaluation(records)}
