"""tester-soft-v1 — KPI timeline shaping (M1.1, raw mode).

Reads the user's finalized v2_sessions and shapes them into the
time-series payload the FE will eventually render on the
"your progress" chart. Ships in RAW MODE for v1: per-session KPI
score, no smoothing, no per-intent cuts. Smoothing (EMA) and intent
cuts come in a follow-up commit once we have ≥3 users with ≥5
sessions and can pick a real α from observed distributions.

Why this lives in its own module
--------------------------------
Two callers expected: the user-facing GET endpoint (now), and the
admin-side "same chart" view of a user's trajectory (next sprint
when admin Tab 1 wants the long view). Keeping the shaping logic
in services/ rather than route layer means both callers reuse
identical aggregation.

Failure semantics
-----------------
- No sessions yet → empty series + summary with sessions_count=0.
- DB hiccup → empty series + a logged warning. Never raises into
  the route; chart renders the empty state.

What's deliberately deferred
----------------------------
- Smoothing (EMA / rolling window) — needs real data to calibrate.
- Per-question-intent cuts ("charisma on stress-framed Q's") —
  requires the snippet→question_intent link to be populated, and
  the question pool to actually be in use.
- Confidence intervals on trend.
- Goal-line / target overlays.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.db import db


logger = logging.getLogger(__name__)


# Cap series length at the request layer. 200 sessions ≈ four years
# of weekly use; well beyond MVP and still cheap to serialize.
_DEFAULT_LIMIT = 200


def build_user_kpi_timeline(
    user_id: str,
    *,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the canonical KPI-timeline payload for ``user_id``.

    Shape::

        {
          "series": [
            {
              "session_id":     "<uuid>",
              "session_date":   "<iso-z>",
              "session_number": 1,
              "kpi_score":      0.42,
              "raw_metrics": {
                  "global_wpm":       float | null,
                  "global_fillers":   int | null,
                  "stickiness_score": float | null
              },
              "source":         "interview" | "audit_upload" | "imported"
            },
            ...
          ],
          "summary": {
            "sessions_count":     int,
            "latest_kpi":         float | null,
            "first_kpi":          float | null,
            "delta_first_to_last": float | null,
            "trend":              "rising" | "falling" | "flat" | "insufficient_data"
          }
        }

    The series is ordered oldest → newest so FE can plot left-to-
    right without re-sorting. ``session_number`` is 1-indexed across
    THIS payload only (so a 200-row cap on a user with 250 sessions
    still numbers them 1..200, not 51..250 — keeps the chart's
    x-axis clean).

    Raw-mode v1: no smoothed_kpi field. When smoothing ships, the
    field name will be additive (`smoothed_kpi` alongside
    `kpi_score`), so the FE chart code doesn't break on the rollout.
    """
    rows = db.get_user_kpi_timeline_rows(user_id, limit=limit) or []

    series: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        kpi = row.get("kpi_score")
        if not isinstance(kpi, (int, float)):
            # Defensive — the query already filters NULL kpi_score,
            # but a future schema drift could let strings through.
            continue
        # AC-9 / split-sink wall (willab handoff §2, §5.1): KPI is
        # PRIVATE-LANE (coach-side, §5 "ISB is coach-side"). It must
        # NEVER be serialized into a user-facing payload. This endpoint
        # is @require_auth (the user's own timeline), so kpi_score and
        # any KPI-derived verdict are stripped here. The user still gets
        # their acoustic trajectory (wpm / fillers / stickiness — all
        # user-facing features per §3.3); only the KPI score/verdict is
        # withheld. ``kpi`` is still read above (and used to FILTER the
        # series to scored sessions) but never emitted.
        series.append({
            "session_id":     row.get("id"),
            "session_date":   row.get("created_at"),
            "session_number": idx,
            "raw_metrics": {
                "global_wpm":       _safe_float(row.get("global_wpm")),
                "global_fillers":   _safe_int(row.get("global_fillers")),
                "stickiness_score": _safe_float(row.get("stickiness_score")),
            },
            # `source` may be absent on pre-foundation-migration rows;
            # default to 'interview' for stable consumer contract.
            "source": row.get("source") or "interview",
        })

    summary = _build_summary(series)
    return {
        "series":  series,
        "summary": summary,
    }


# ── Internals ──────────────────────────────────────────────────────


def _build_summary(series: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline stats for the shaped series.

    AC-9 / split-sink wall: the previous version emitted
    latest_kpi / first_kpi / delta_first_to_last / a KPI-derived
    ``trend`` verdict — all PRIVATE-LANE (KPI is coach-side, §5).
    Those are removed; the user-facing summary carries only the
    non-leaky session count. A future user-facing progress signal,
    if wanted, must be built from acoustic features (wpm / fillers
    / stickiness), never from KPI.
    """
    return {
        "sessions_count": len(series),
    }


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):  # bool is int subclass; reject.
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
