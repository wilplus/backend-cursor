"""Queue saturation signal — the number that decides worker sizing.

Answers one operational question: **is anyone waiting?** More workers can
only ever shrink the WAIT (enqueued → started). They cannot shrink the RUN
(started → finished), which is Whisper plus the LLM calls and is fixed by
the pipeline, not the fleet. Scaling on run time is the classic mistake —
you pay for containers and the takes are exactly as slow as before.

So the verdict compares wait against run:

  healthy    nothing pending; every take starts immediately
  busy       work is queued but waits are short next to a take's own time
  saturated  people wait about as long as the work itself takes → add slots

OPS ONLY. Secret-gated, never user-facing: these are plumbing counters
about jobs, not reads on a speaker, and surfacing "we're busy" to users is
product copy that needs founder sign-off (CLAUDE.md).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.db import db

logger = logging.getLogger(__name__)

# Sample size for the latency percentiles. Bounded on purpose: this runs on
# an ops poke and inside the worker's 5-minute sweep, and neither should
# ever pull an unbounded table scan.
_SAMPLE_ROWS = 200

# Failures are counted over a TIME window, not the row sample: "4 failures"
# should mean "4 in the last day", not "4 somewhere in the last 200 jobs",
# which at low volume keeps a long-fixed outage in the number for months.
_DEFAULT_FAILURE_WINDOW_HOURS = 24


def failure_window_hours() -> int:
    raw = (os.getenv("PIPELINE_FAILURE_WINDOW_HOURS") or "").strip()
    try:
        return max(1, int(raw)) if raw else _DEFAULT_FAILURE_WINDOW_HOURS
    except ValueError:
        return _DEFAULT_FAILURE_WINDOW_HOURS


def _age_seconds(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def _elapsed(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return max(0.0, (b - a).total_seconds())


def _percentile(values: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile. No numpy — this must stay importable in the
    web process without dragging the analysis stack in."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(pct * len(ordered) + 0.5)) - 1))
    return round(ordered[idx], 1)


def queue_health(sample_rows: int = _SAMPLE_ROWS) -> Dict[str, Any]:
    """Snapshot + verdict. Never raises — an ops probe must not 500."""
    out: Dict[str, Any] = {
        "queue": {"pending": 0, "processing": 0,
                  "oldest_pending_seconds": None},
        "latency": {"sample": 0, "wait_p50_s": None, "wait_p95_s": None,
                    "run_p50_s": None, "run_p95_s": None},
        "failures": {"recent": 0, "last_error": None},
        "saturation": "healthy",
        "recommendation": "",
    }

    active = []
    try:
        active = db.list_active_processing_jobs(max_rows=500) or []
    except Exception as e:
        logger.warning("queue_health: active query failed: %s", e)
        out["saturation"] = "unknown"
        out["recommendation"] = "could not read the queue"
        return out

    pending = [j for j in active if str(j.get("status")) == "pending"]
    processing = [j for j in active if str(j.get("status")) == "processing"]
    ages = [a for a in (_age_seconds(j.get("enqueued_at")) for j in pending)
            if a is not None]
    oldest = round(max(ages), 1) if ages else None
    out["queue"] = {
        "pending": len(pending),
        "processing": len(processing),
        "oldest_pending_seconds": oldest,
    }

    recent = []
    try:
        recent = db.list_recent_finished_processing_jobs(
            max_rows=sample_rows) or []
    except Exception as e:
        logger.warning("queue_health: history query failed: %s", e)

    # Failures are TIME-windowed; latency is SAMPLE-windowed. They answer
    # different questions and want different windows:
    #
    #   "is it failing NOW?"        → last N hours. A count over the last
    #     200 rows means a bad afternoon stays in the number for months at
    #     low volume, long after it stopped being true.
    #   "how long does a take take?" → last N rows. Percentiles need a
    #     sample, and a time window returns nothing on a quiet day.
    cutoff = failure_window_hours() * 3600.0
    waits, runs, failures, last_error = [], [], 0, None
    for j in recent:
        if str(j.get("status")) == "failed":
            age = _age_seconds(j.get("finished_at"))
            # Unparseable timestamp: count it. Better a stale number than a
            # silently dropped failure.
            if age is None or age <= cutoff:
                failures += 1
                last_error = last_error or j.get("error")
            continue
        w = _elapsed(j.get("enqueued_at"), j.get("started_at"))
        r = _elapsed(j.get("started_at"), j.get("finished_at"))
        if w is not None:
            waits.append(w)
        if r is not None:
            runs.append(r)

    out["latency"] = {
        "sample": len(runs),
        "wait_p50_s": _percentile(waits, 0.50),
        "wait_p95_s": _percentile(waits, 0.95),
        "run_p50_s": _percentile(runs, 0.50),
        "run_p95_s": _percentile(runs, 0.95),
    }
    # window_hours is reported so the number is self-describing — "4" means
    # nothing without knowing "4 in what span".
    out["failures"] = {"recent": failures,
                       "window_hours": failure_window_hours(),
                       "last_error": (str(last_error)[:300]
                                      if last_error else None)}

    # The verdict. run_p50 is the yardstick: a wait is "bad" relative to how
    # long the work itself takes, not against any absolute number — a 30s
    # wait is nothing beside a 10-minute take and painful beside a 30s one.
    run_p50 = out["latency"]["run_p50_s"]
    if not pending:
        out["saturation"] = "healthy"
        out["recommendation"] = (
            "nothing queued — every take starts immediately. Adding workers "
            "would change nothing."
        )
    elif run_p50 and oldest is not None and oldest >= run_p50:
        out["saturation"] = "saturated"
        out["recommendation"] = (
            f"{len(pending)} take(s) queued and the oldest has waited "
            f"{oldest}s, at or beyond the {run_p50}s a take itself takes. "
            f"Raise WORKER_COUNT (or add a worker replica)."
        )
    else:
        out["saturation"] = "busy"
        out["recommendation"] = (
            f"{len(pending)} take(s) queued but waits are still short next "
            f"to a take's own time — working through it, no action needed."
        )
    return out


def log_saturation(health: Optional[Dict[str, Any]] = None) -> str:
    """Emit the verdict to the logs so saturation shows up in Railway
    without anyone running SQL. Returns the verdict."""
    h = health if health is not None else queue_health()
    verdict = str(h.get("saturation") or "unknown")
    if verdict == "saturated":
        logger.warning("pipeline queue SATURATED: %s | %s",
                       h.get("queue"), h.get("recommendation"))
    elif verdict == "busy":
        logger.info("pipeline queue busy: %s", h.get("queue"))
    return verdict
