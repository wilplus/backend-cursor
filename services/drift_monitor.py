"""Drift monitoring — PSI on inputs, p-chart on decisions.

SPEC.md v3 D26/D30, Appendix G §G.5 / §G.7 / §G.9. Build prompt:
docs/PROMPT-drift-layer.md. Operational process: PM-3.

WHAT THIS IS, AND WHAT IT IS NOT (Appendix G.1.1 — read before trusting it).
This is a REGRESSION detector. It answers "did something change under us" —
an ASR upgrade, a VAD change, a segmentation edit shifting word bucketing.
It CANNOT answer "is this dimension measuring anything real", because there
is no external criterion anywhere in the loop. A green dashboard means
NOTHING MOVED. It never means the dimensions are right. Correctness runs
through human labels, which is the ~15/week bottleneck (SPEC §1).

NOT the same thing as metrics_v2.detect_classifier_drift. That compares two
scores ON ONE RECORDING and asks whether they agree. This compares a
DISTRIBUTION over many recordings against a frozen reference. Same word,
different question; do not wire one to the other.

THE PAIR IS THE DIAGNOSIS. Neither monitor alone says what broke:

    PSI (inputs)  p-chart (decisions)   reading
    stable        stable                HEALTHY
    shifted       stable                POPULATION_MOVED
    stable        out of control        PIPELINE_CHANGED   <- the one we exist for
    shifted       out of control        UPSTREAM_CHANGE

PIPELINE_CHANGED is a stable input distribution with drifting decisions:
our own code moved. That is the failure this layer exists to catch, and it
is the one nobody would otherwise notice.

AC-9. Nothing here is user-facing. No PSI value, decile, fire rate or
control limit may enter a client-facing schema or any user-visible copy.
Internal audit surface only.

Pure: no DB, no I/O, unit-tested.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

# ── PSI ─────────────────────────────────────────────────────────────────────

DECILES = tuple(range(1, 11))

# Appendix G.7. The industry-standard bands; MAJOR means retire or refit the
# reference, which mints a new frozen version rather than editing the old one.
PSI_STABLE_BELOW = 0.10
PSI_MAJOR_AT = 0.20

STABLE = "STABLE"
MODERATE_SHIFT = "MODERATE_SHIFT"
MAJOR_SHIFT_REFIT = "MAJOR_SHIFT_REFIT"
INSUFFICIENT_N = "INSUFFICIENT_N"


def _normalise(counts: Mapping[Any, Any]) -> tuple[dict[int, float], int]:
    """Counts per decile -> (proportions, n). Unknown/!1..10 keys dropped.

    Takes COUNTS, not proportions, on purpose: n is needed for the smoothing
    below, and a caller who passes proportions where counts are expected
    would otherwise get a silently wrong smoothing floor rather than an
    error.
    """
    clean: dict[int, float] = {}
    total = 0
    for k, v in (counts or {}).items():
        try:
            decile = int(k)
            value = float(v)
        except (TypeError, ValueError):
            continue
        if decile not in DECILES or value < 0 or not math.isfinite(value):
            continue
        clean[decile] = value
        total += value
    if total <= 0:
        return {}, 0
    return {d: clean.get(d, 0.0) / total for d in DECILES}, int(total)


def _smooth(pct: float, n: int) -> float:
    """Additive smoothing so an empty decile does not make PSI infinite.

    ln(0) is -inf, so a decile that is empty on either side would blow the
    whole statistic up. DROPPING such a decile instead (the obvious
    alternative) is worse in a specific way: an empty decile is usually the
    strongest evidence of a shift, so dropping it UNDERSTATES the very
    number you are computing. Floor it at half an observation.
    """
    if n <= 0:
        return 0.0
    return max(pct, 0.5 / n)


def psi(current_counts: Mapping[Any, Any],
        reference_counts: Mapping[Any, Any]) -> Optional[float]:
    """Population Stability Index between two decile histograms.

        PSI = sum_i (actual_i - expected_i) * ln(actual_i / expected_i)

    Both arguments are COUNTS per decile (1..10). Returns None when either
    side is empty — "no data" is not "no drift", and returning 0.0 there
    would read as a clean bill of health.
    """
    cur, n_cur = _normalise(current_counts)
    ref, n_ref = _normalise(reference_counts)
    if not cur or not ref:
        return None

    total = 0.0
    for d in DECILES:
        a = _smooth(cur.get(d, 0.0), n_cur)
        e = _smooth(ref.get(d, 0.0), n_ref)
        total += (a - e) * math.log(a / e)
    return round(total, 6)


def psi_verdict(value: Optional[float], *, n_current: int = 0,
                min_n: int = 20) -> str:
    """Band a PSI value. Small samples report INSUFFICIENT_N rather than a
    verdict — PSI on a handful of observations is dominated by the smoothing
    floor, and acting on it would mean chasing noise."""
    if value is None:
        return INSUFFICIENT_N
    if n_current and n_current < min_n:
        return INSUFFICIENT_N
    if value < PSI_STABLE_BELOW:
        return STABLE
    if value < PSI_MAJOR_AT:
        return MODERATE_SHIFT
    return MAJOR_SHIFT_REFIT


# ── p-chart ─────────────────────────────────────────────────────────────────

IN_CONTROL = "IN_CONTROL"
OUT_OF_CONTROL_HIGH = "OUT_OF_CONTROL_HIGH"
OUT_OF_CONTROL_LOW = "OUT_OF_CONTROL_LOW"

# Western Electric rule 2 — a run this long on one side of the centre line is
# a signal even when every point sits inside the limits. Slow drift never
# breaches 3-sigma; it just stops crossing the middle.
RUN_LENGTH = 8

# Below this the 3-sigma limits are so wide they can never be breached, so a
# green chart would be an artefact of sample size rather than a finding.
MIN_WEEKLY_N = 20


def p_chart(weekly: Sequence[Mapping[str, Any]], *,
            min_n: int = MIN_WEEKLY_N) -> dict:
    """Shewhart p-chart over weekly fire rates.

    ``weekly`` is a sequence of ``{"week": <label>, "n": int, "fired": int}``
    IN CHRONOLOGICAL ORDER — the run rule depends on the ordering, so an
    unsorted input silently produces a meaningless run signal.

    CALLER'S RESPONSIBILITY, and it is not optional: pass ABSOLUTE (T1/T2)
    benchmarks only. For CORPUS_REL the fire rate is pinned by construction
    (Appendix G.5) — a 10th-percentile threshold fails ~10% of the time
    definitionally, so charting it yields a monitor that can never signal
    while looking perfectly healthy.

        CL  = p_bar                                  (weighted by weekly n)
        UCL = p_bar + 3*sqrt(p_bar*(1-p_bar)/n_bar)
        LCL = max(0, p_bar - 3*sqrt(...))
    """
    points: list[dict] = []
    total_fired = 0
    total_n = 0
    for row in weekly or ():
        try:
            n = int(row.get("n") or 0)
            fired = int(row.get("fired") or 0)
        except (TypeError, ValueError):
            continue
        if n <= 0 or fired < 0 or fired > n:
            continue
        points.append({"week": row.get("week"), "n": n, "fired": fired,
                       "p_hat": fired / n})
        total_fired += fired
        total_n += n

    if not points or total_n <= 0:
        return {"centre_line": None, "ucl": None, "lcl": None,
                "points": [], "signal": INSUFFICIENT_N, "n_total": 0}

    p_bar = total_fired / total_n
    n_bar = total_n / len(points)

    if n_bar < min_n:
        for p in points:
            p["signal"] = INSUFFICIENT_N
        return {"centre_line": round(p_bar, 6), "ucl": None, "lcl": None,
                "points": points, "signal": INSUFFICIENT_N, "n_total": total_n}

    sigma = math.sqrt(max(p_bar * (1.0 - p_bar), 0.0) / n_bar)
    ucl = min(1.0, p_bar + 3.0 * sigma)
    lcl = max(0.0, p_bar - 3.0 * sigma)

    breached = False
    for p in points:
        if p["p_hat"] > ucl:
            p["signal"] = OUT_OF_CONTROL_HIGH      # too strict, or quality dropped
            breached = True
        elif p["p_hat"] < lcl:
            p["signal"] = OUT_OF_CONTROL_LOW       # too lax, or nothing to find
            breached = True
        else:
            p["signal"] = IN_CONTROL

    run_side = _run_violation(points, p_bar)
    if run_side:
        breached = True

    return {
        "centre_line": round(p_bar, 6),
        "ucl": round(ucl, 6),
        "lcl": round(lcl, 6),
        "n_total": total_n,
        "points": points,
        "run_violation": run_side,
        "signal": (OUT_OF_CONTROL_HIGH if run_side == "high"
                   else OUT_OF_CONTROL_LOW if run_side == "low"
                   else OUT_OF_CONTROL_HIGH if any(
                       p["signal"] == OUT_OF_CONTROL_HIGH for p in points)
                   else OUT_OF_CONTROL_LOW if any(
                       p["signal"] == OUT_OF_CONTROL_LOW for p in points)
                   else IN_CONTROL),
        "breached": breached,
    }


def _run_violation(points: Sequence[Mapping[str, Any]],
                   p_bar: float) -> Optional[str]:
    """RUN_LENGTH consecutive points on one side of the centre line.

    Catches the drift 3-sigma limits miss entirely: a threshold that slid a
    little never breaches a limit, it just stops crossing the middle.
    Points exactly on the line break a run rather than extending it.
    """
    high = low = 0
    for p in points:
        if p["p_hat"] > p_bar:
            high, low = high + 1, 0
        elif p["p_hat"] < p_bar:
            low, high = low + 1, 0
        else:
            high = low = 0
        if high >= RUN_LENGTH:
            return "high"
        if low >= RUN_LENGTH:
            return "low"
    return None


# ── the PM-3 2x2 ────────────────────────────────────────────────────────────

HEALTHY = "HEALTHY"
POPULATION_MOVED = "POPULATION_MOVED"
PIPELINE_CHANGED = "PIPELINE_CHANGED"
UPSTREAM_CHANGE = "UPSTREAM_CHANGE"
UNKNOWN = "UNKNOWN"

_TRIAGE_PRIORITY = {
    PIPELINE_CHANGED: 0,     # our own code moved — triage first
    UPSTREAM_CHANGE: 1,
    POPULATION_MOVED: 2,
    UNKNOWN: 3,
    HEALTHY: 4,
}


def triage(psi_band: str, chart_signal: str) -> str:
    """The PM-3 2x2. Emit THIS, not two independent numbers — the pair is the
    diagnosis and reading either alone points at the wrong cause."""
    if psi_band == INSUFFICIENT_N or chart_signal == INSUFFICIENT_N:
        return UNKNOWN
    psi_shifted = psi_band in (MODERATE_SHIFT, MAJOR_SHIFT_REFIT)
    chart_bad = chart_signal in (OUT_OF_CONTROL_HIGH, OUT_OF_CONTROL_LOW)
    if psi_shifted and chart_bad:
        return UPSTREAM_CHANGE
    if chart_bad:
        return PIPELINE_CHANGED
    if psi_shifted:
        return POPULATION_MOVED
    return HEALTHY


def rank_triage(verdicts: Iterable[str]) -> list[str]:
    """Most-urgent first, so a report leads with PIPELINE_CHANGED rather than
    burying it under a page of HEALTHY rows."""
    return sorted(verdicts, key=lambda v: _TRIAGE_PRIORITY.get(v, 3))
