"""The fair-test calculator: would a new ranker help more people? (step 8 prep)

Grades a candidate exercise ranker against today's fixed ranking under
exercise-adequacy-label-v1 (founder 2026-09-28,
docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5), without ever serving it:

  * **Study group and exam group (item 6).** Speakers are split by a stable
    hash of the speaker id. A ranker may learn only from `split_of(...) ==
    "train"` speakers; it is graded only on `"holdout"` speakers.
  * **Off-policy estimate (item 7).** Each 80/20 draw stored every eligible
    exercise's probability (0372). A candidate is credited only on exposures
    where it would have chosen the exercise that was actually served,
    weighted by 1 / that probability (inverse-propensity weighting).
  * **Two rates, never pooled (items 5, 7).** The attempt rate is estimated
    over every cohort exposure; the success rate is the share helped among
    exposures with a valid endpoint — the ratio of the two weighted sums — so
    a missing attempt is never read as "didn't help".
  * **95% intervals by resampling speakers**, not exposures (item 7).
  * **The bar (item 9):** success at least 5 points higher with the
    interval of the difference above zero, attempt rate at most 5 points
    lower. Meeting it proposes, never promotes: the founder approves, and even
    then a ranker only reorders the already-safe pool.

SEALED like the scorekeeper: `evaluate()` answers only "sealed" and why
until the evidence bar (item 8) is met. `compare()` stays pure for fixtures.
Once the bar is met the full jar unseals the evaluation on its own (founder
2026-09-29): services/exercise_evaluation grades its first candidate here
and shows the result on the founder's jar page. Nothing promotes.
Internal only: the founder's CMS page, through services/exercise_evaluation;
no number here reaches a speaker or a coach.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, Callable, Optional

from services.exercise_adequacy_labels import label
from services.exercise_learning_readiness import (
    LABEL_SPEC_VERSION,
    cohort_records,
    read_sources,
    readiness,
)

FAIR_TEST_VERSION = "exercise-fair-test-v1"
SPLIT_VERSION = "exercise-speaker-split-v1"
#: Share of speakers held out for grading (founder 2026-09-28: keep 30%).
#: Changing it changes SPLIT_VERSION and is the founder's call.
HOLDOUT_SHARE = 0.3
#: §3.5 item 9 (founder 2026-09-28).
MIN_SUCCESS_GAIN = 0.05
MAX_ATTEMPT_DROP = 0.05
BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20260928

Choose = Callable[[dict], Optional[str]]


def split_of(speaker_id: str) -> str:
    """"train" or "holdout", the same for a speaker forever (per version)."""
    digest = hashlib.sha256(f"{SPLIT_VERSION}:{speaker_id}".encode()).hexdigest()
    return "holdout" if int(digest[:8], 16) / 0x100000000 < HOLDOUT_SHARE \
        else "train"


def logged_odds(assignment: Any) -> dict[str, float]:
    """Each eligible exercise's probability in this draw, as stored (0372)."""
    odds: dict[str, float] = {}
    for row in (assignment or {}).get("candidates") or ():
        if not isinstance(row, dict):
            continue
        num, den = row.get("probability_numerator"), row.get("probability_denominator")
        if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den > 0:
            odds[str(row.get("exercise_id"))] = float(num) / float(den)
    return odds


def fixed_ranking(unit: dict) -> Optional[str]:
    """Today's policy without exploration: the top-ranked eligible exercise."""
    return unit["pool"][0] if unit["pool"] else None


def units_from(records: list[dict]) -> list[dict]:
    """One evaluation unit per cohort exposure. Pure."""
    units = []
    for record in records:
        if not record["in_cohort"]:
            continue
        exposure, assignment = record["exposure"], record["assignment"]
        if str(assignment.get("selection_mode") or "") == "coach_chosen":
            # A coach's pick (0398) was not drawn from a ranked pool with
            # logged odds, so no policy can be compared on it. It counts in
            # the jar; it is not an evaluation unit.
            continue
        ranked = sorted((r for r in assignment.get("candidates") or ()
                         if isinstance(r, dict)),
                        key=lambda r: int(r.get("rank") or 0))
        counted = record["excluded"] is None
        units.append({
            "speaker": str(exposure.get("owner_user_id") or ""),
            "served": str(exposure.get("exercise_id") or ""),
            "pool": [str(r.get("exercise_id")) for r in ranked],
            "odds": logged_odds(assignment),
            "trace": record["trace"],
            "attempted": counted,
            "helped": bool(label(record)["helped"]) if counted else None,
        })
    return units


def policy_rates(units: list[dict], choose: Choose) -> dict[str, Optional[float]]:
    """(attempt rate, success rate) the policy would get, by inverse-propensity
    weighting on the stored odds. None where nothing matched."""
    tried = helped = 0.0
    for unit in units:
        p = unit["odds"].get(unit["served"])
        if not p or choose(unit) != unit["served"]:
            continue
        if unit["attempted"]:
            tried += 1.0 / p
            if unit["helped"]:
                helped += 1.0 / p
    n = len(units)
    return {"attempt_rate": tried / n if n else None,
            "success_rate": helped / tried if tried else None}


def _diff(units: list[dict], candidate: Choose,
          baseline: Choose) -> tuple[Optional[float], Optional[float]]:
    a, b = policy_rates(units, candidate), policy_rates(units, baseline)

    def minus(key: str) -> Optional[float]:
        x, y = a[key], b[key]
        return None if x is None or y is None else x - y
    return minus("success_rate"), minus("attempt_rate")


def _interval(units: list[dict], candidate: Choose,
              baseline: Choose) -> Optional[tuple[float, float]]:
    """95% percentile interval of the success difference, resampling speakers."""
    by_speaker: dict[str, list[dict]] = {}
    for unit in units:
        by_speaker.setdefault(unit["speaker"], []).append(unit)
    speakers = sorted(by_speaker)
    if not speakers:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    diffs = []
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = [u for s in rng.choices(speakers, k=len(speakers))
                  for u in by_speaker[s]]
        gain, _drop = _diff(sample, candidate, baseline)
        if gain is not None:
            diffs.append(gain)
    if len(diffs) < BOOTSTRAP_ROUNDS // 2:
        return None
    diffs.sort()
    return (diffs[int(0.025 * (len(diffs) - 1))],
            diffs[int(0.975 * (len(diffs) - 1))])


def compare(units: list[dict], candidate: Choose,
            baseline: Choose = fixed_ranking) -> dict:
    """Grade `candidate` against `baseline` on held-out speakers. Pure."""
    held = [u for u in units if split_of(u["speaker"]) == "holdout"]
    gain, change = _diff(held, candidate, baseline)
    interval = _interval(held, candidate, baseline)
    reasons = []
    if gain is None or gain < MIN_SUCCESS_GAIN:
        reasons.append(f"success gain below {MIN_SUCCESS_GAIN:.0%}")
    if interval is None or interval[0] <= 0:
        reasons.append("interval of the gain not above zero")
    if change is None or change < -MAX_ATTEMPT_DROP:
        reasons.append(f"attempt rate falls more than {MAX_ATTEMPT_DROP:.0%}")
    return {
        "label_spec_version": LABEL_SPEC_VERSION,
        "fair_test_version": FAIR_TEST_VERSION,
        "split_version": SPLIT_VERSION,
        "holdout": {"exposures": len(held),
                    "speakers": len({u["speaker"] for u in held}),
                    "candidate_agrees": sum(1 for u in held
                                            if candidate(u) == u["served"])},
        "candidate": policy_rates(held, candidate),
        "baseline": policy_rates(held, baseline),
        "success_gain": gain,
        "success_gain_interval_95": list(interval) if interval else None,
        "attempt_rate_change": change,
        "meets_bar": not reasons,
        "why_not": reasons,
        "requires_founder_approval": True,
    }


def evaluate(database: Any, candidate: Choose) -> dict:
    """The fair test on live data, once the evidence bar is met."""
    from services.confident_voice_practice import SIGNAL_RULES_VERSION
    gate = readiness(database)
    if not gate.get("ready"):
        return {"sealed": True, "why_not": gate.get("why_not")}
    rows, unavailable = read_sources(database)
    if unavailable:
        return {"sealed": True, "why_not": "unreadable: " + ", ".join(unavailable)}
    records = cohort_records(signal_rules_version=SIGNAL_RULES_VERSION, **rows)
    return {"sealed": False, **compare(units_from(records), candidate)}
