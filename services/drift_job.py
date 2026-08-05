"""The weekly drift run — orchestration for PM-3.

SPEC.md v3 D26/D30, Appendix G §G.5/§G.7/§G.9. Pure maths lives in
services/drift_monitor; the registry owns every spec fact
(services/dimension_registry). This module is I/O and sequencing only.

WHAT IT DOES, IN ORDER
  1. Read `dimension_evaluations` for the window.
  2. AGGREGATE TO SESSION GRAIN. Not optional — see below.
  3. If no frozen reference exists and there is enough data, MINT one.
  4. Otherwise bucket the current values against the frozen CUT POINTS and
     compute PSI per dimension.
  5. Build a p-chart from the decision rows (ABSOLUTE tiers, `fired` present).
  6. Emit the PM-3 2x2 per dimension, most urgent first.

THE GRAIN RULE, WHICH THE SCHEMA CANNOT ENFORCE. Snippets inside a session are
not independent: one user recording thirty snippets in a sitting contributes
thirty correlated rows. Counting them as thirty observations inflates n,
narrows the p-chart's control limits by roughly sqrt(30), and makes PSI
confident about a "shift" that is one person having a long day — the monitor
then fires on its own sampling, which is how a monitor gets switched off and
ignored. Every read here collapses to one value per (session, dimension)
first.

WHAT THIS IS AND IS NOT (Appendix G.1.1). A REGRESSION detector. It answers
"did something change under us" — an ASR upgrade, a VAD change, a
segmentation edit shifting word bucketing. It cannot answer "is this dimension
measuring anything real", because no external criterion is in the loop. A
green report means NOTHING MOVED. It never means the dimensions are right.

AC-9. Nothing here is user-facing. No PSI value, decile, fire rate or control
limit may enter a client-facing schema or any user-visible copy.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Appendix G.7 — the reference is built from the first complete weeks and then
# FROZEN. Minting early gives a baseline that is mostly noise; minting late
# means no PSI at all. Four weeks is the appendix's figure.
REFERENCE_WEEKS = 4
DEFAULT_VERSION = "frozen_v1"

# Below this a decile split is meaningless — ten buckets over a handful of
# sessions puts one observation in each and PSI reads whatever the sampling
# did. Refuse rather than mint a reference nobody should compare against.
MIN_SESSIONS_TO_MINT = 40


def _session_values(rows: Any) -> dict[str, dict[str, float]]:
    """{dimension_id: {session_id: mean raw_value}} — THE GRAIN RULE.

    Aggregation per dimension comes from the registry, so a dimension declared
    `per_minute` is not silently averaged like a level. Rows flagged
    `insufficient_data` are dropped here: they carry no value by construction
    (SPEC D30), and averaging a None into a session would invent one.
    """
    from services import dimension_registry as registry

    buckets: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    for r in rows or ():
        if r.get("insufficient_data"):
            continue
        value = r.get("raw_value")
        dim = r.get("dimension_id")
        session = r.get("session_id")
        if value is None or not dim or not session:
            continue
        try:
            buckets[str(dim)][str(session)].append(float(value))
        except (TypeError, ValueError):
            continue

    out: dict[str, dict[str, float]] = {}
    for dim, sessions in buckets.items():
        how = registry.aggregation_of(dim) or "mean"
        collapsed: dict[str, float] = {}
        for session, values in sessions.items():
            if not values:
                continue
            # `sum` and the rate forms all roll up additively across a
            # session; levels average. The registry decides which, so this
            # file never restates Appendix F.4.
            collapsed[session] = (sum(values) if how in ("sum", "per_minute",
                                                        "per_1000_words")
                                  else sum(values) / len(values))
        if collapsed:
            out[dim] = collapsed
    return out


def _mint_reference(session_values: dict[str, dict[str, float]],
                    *, version: str) -> list[dict]:
    """Decile cut points per dimension, for insertion.

    `upper_bound` is what a later raw value is bucketed against; `pct` is the
    expected mass, ~0.1 by construction for a decile split. Both are stored
    because a future non-decile binning would have non-uniform mass, and
    because pct alone cannot assign a decile (that was a defect in 0247).
    """
    rows: list[dict] = []
    for dim, sessions in session_values.items():
        values = sorted(sessions.values())
        n = len(values)
        if n < MIN_SESSIONS_TO_MINT:
            logger.info("drift_job: %s has %d sessions, need %d to mint",
                        dim, n, MIN_SESSIONS_TO_MINT)
            continue
        for decile in range(1, 11):
            hi_idx = int(round(decile * n / 10.0)) - 1
            hi_idx = max(0, min(n - 1, hi_idx))
            rows.append({
                "version": version,
                "dimension_id": dim,
                "decile": decile,
                "pct": 0.1,
                # Decile 10 is +infinity: anything above the ninth cut point
                # belongs there, and a finite bound would drop new extremes.
                "upper_bound": None if decile == 10 else values[hi_idx],
                "n_at_freeze": n,
            })
    return rows


def _bucket(value: float, cuts: list[tuple[int, Optional[float]]]) -> int:
    """Assign a value to a decile using the frozen cut points."""
    for decile, upper in cuts:
        if upper is not None and value <= upper:
            return decile
    return 10


def run_weekly(*, weeks: int = 4, version: str = DEFAULT_VERSION) -> dict:
    """One drift run. Never raises — a monitor that can crash the thing it
    monitors is worse than no monitor."""
    from services import dimension_registry as registry
    from services import drift_monitor as dm
    from services.db import db

    report: dict[str, Any] = {"version": version, "dimensions": {},
                              "minted": 0, "note": None}
    try:
        rows = db.get_dimension_evaluations_since(weeks=max(weeks, REFERENCE_WEEKS))
    except Exception as e:
        logger.warning("drift_job: read failed: %s", e)
        report["note"] = f"read failed: {e}"
        return report

    if not rows:
        report["note"] = "no evaluations yet — telemetry has not accumulated"
        return report

    session_values = _session_values(rows)
    report["sessions_by_dimension"] = {d: len(v) for d, v in session_values.items()}

    reference = db.get_reference_distribution(version)
    if not reference:
        minted = _mint_reference(session_values, version=version)
        if minted:
            report["minted"] = db.insert_reference_distribution(minted)
            report["note"] = (f"minted {version} from "
                              f"{report['minted'] // 10} dimension(s); PSI "
                              f"starts from the NEXT run — comparing a "
                              f"reference against the data it was built from "
                              f"would read 0.0 by construction")
        else:
            report["note"] = (f"not enough data to mint {version} "
                              f"(need {MIN_SESSIONS_TO_MINT} sessions per "
                              f"dimension)")
        return report

    cuts: dict[str, list[tuple[int, Optional[float]]]] = defaultdict(list)
    ref_counts: dict[str, dict[int, int]] = defaultdict(dict)
    for r in reference:
        dim = str(r.get("dimension_id"))
        decile = int(r.get("decile") or 0)
        cuts[dim].append((decile, r.get("upper_bound")))
        n_at_freeze = int(r.get("n_at_freeze") or 0)
        ref_counts[dim][decile] = int(round(float(r.get("pct") or 0.0)
                                            * n_at_freeze))
    for dim in cuts:
        cuts[dim].sort()

    # p-chart input: ABSOLUTE tiers with a real decision, weekly, session grain.
    weekly: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"n": 0, "fired": 0}))
    seen_sessions: dict[str, set] = defaultdict(set)
    for r in rows or ():
        if r.get("insufficient_data") or r.get("fired") is None:
            continue
        if str(r.get("benchmark_tier")) not in ("T1", "T2"):
            continue
        dim, session = str(r.get("dimension_id")), str(r.get("session_id"))
        week = str(r.get("evaluated_at") or "")[:10]
        key = (dim, session, week)
        if key in seen_sessions[dim]:
            continue
        seen_sessions[dim].add(key)
        bucket = weekly[dim][week]
        bucket["n"] += 1
        if r.get("fired"):
            bucket["fired"] += 1

    for dim, sessions in session_values.items():
        if dim not in cuts:
            continue
        current: dict[int, int] = defaultdict(int)
        for value in sessions.values():
            current[_bucket(value, cuts[dim])] += 1

        psi_value = dm.psi(dict(current), ref_counts[dim])
        band = dm.psi_verdict(psi_value, n_current=len(sessions))

        series = [{"week": w, **counts}
                  for w, counts in sorted(weekly.get(dim, {}).items())]
        chart: dict = (dm.p_chart(series) if series
                       else {"signal": dm.INSUFFICIENT_N})

        d = registry.get(dim)
        report["dimensions"][dim] = {
            "psi": psi_value,
            "psi_band": band,
            "n_sessions": len(sessions),
            "chart_signal": chart.get("signal"),
            "chartable": registry.is_chartable(dim),
            "window_class": d.window_class if d else None,
            "triage": dm.triage(band, str(chart.get("signal") or dm.INSUFFICIENT_N)),
        }

    ranked = dm.rank_triage(v["triage"] for v in report["dimensions"].values())
    report["worst"] = ranked[0] if ranked else None
    return report
