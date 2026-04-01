"""Shared utilities for the backend."""
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now_iso() -> str:
    """Return the current UTC time as a Z-suffixed ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def score_01_from_recording_row(rec: Any) -> Optional[float]:
    """Read 0..1 score from recordings.performance_metrics_v2.scoring_debug (set by recording_1/2 job)."""
    if not isinstance(rec, dict):
        return None
    pm = rec.get("performance_metrics_v2")
    if not isinstance(pm, dict):
        return None
    dbg = pm.get("scoring_debug")
    if not isinstance(dbg, dict):
        return None
    for key in ("score_01", "final_score_01"):
        v = dbg.get(key)
        if v is None:
            continue
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            continue
    return None
