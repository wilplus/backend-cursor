"""Candidate detectors, built and not trained (founder 2026-10-01; Phase 6d
of the coach panel; E3). Gated: training is Phase-2 work under PLF1 and
stays off; counsel is asked whether tuning a cut-off counts as training
under C1 (a learned model does).

Two candidates per error, both reading STORED SNAPSHOTS and never raw audio
at first:
  * ``tuned-v1``: the same signals as rules-v1 with cut-offs a reviewed PR
    may set from the blind answers (Phase 6a's report card); registered in
    SHADOW with detector_rollout, graded by the fair test (6c), never live
    but by LIVE_DETECTOR after the founder's yes.
  * ``learned-v1``: a per-error model on snapshot features. The skeleton is
    here; ``fit`` refuses while Config.DETECTOR_TRAINING_AUTHORISED is False,
    and ``score`` answers None until a model exists.

THE RE-SCORE JOB (E3): on a switch, old clips and attempts are re-scored
from their stored snapshots under the new version, silently into the shadow
log (insert-once), so the jar keeps its history across a flip; the live
re-score waits for the founder's yes.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

TUNED_VERSION = "tuned-v1"
LEARNED_VERSION = "learned-v1"
#: Cut-offs a reviewed PR sets from the report card. Until then they equal
#: rules-v1's, so the candidate is a copy that can be graded end to end.
TUNED_THRESHOLDS: dict[str, dict[str, float]] = {
    "rushing": {"pause_ratio_lt": 0.08, "pause_regularity_lt": 0.5},
    "word_compression": {"median_gap_lt": 0.07, "tight_gap_share_ge": 0.5,
                         "word_occupancy_gt": 0.78, "word_recognition_confidence_lt": 0.82},
    "ending_compression": {"ending_duration_ratio_lt": 0.78},
}


class NotAuthorised(RuntimeError):
    """Training a detector is Phase-2 work under PLF1; it is off."""


def training_authorised() -> bool:
    from config import Config
    return bool(getattr(Config, "DETECTOR_TRAINING_AUTHORISED", False))


def _num(snapshot: dict, key: str) -> Optional[float]:
    value = snapshot.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def tuned(error_id: str, snapshot: Any) -> Optional[bool]:
    """The tuned candidate's verdict; None when nothing is measurable."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    cuts = TUNED_THRESHOLDS.get(error_id)
    if not cuts:
        return None
    checks: list[bool] = []
    for name, cut in cuts.items():
        key, op = name.rsplit("_", 1)
        value = _num(snap, key)
        if value is None:
            continue
        checks.append(value < cut if op == "lt" else value > cut if op == "gt" else value >= cut)
    return any(checks) if checks else None


class LearnedDetector:
    """A per-error model on snapshot features. Nothing trains it until the
    founder and counsel say so; until then it scores nothing."""

    FEATURES = ("wpm", "pause_ratio", "pause_regularity", "median_gap", "tight_gap_share",
                "word_occupancy", "word_recognition_confidence", "ending_duration_ratio")

    def __init__(self, error_id: str) -> None:
        self.error_id = error_id
        self.weights: Optional[dict[str, float]] = None

    def fit(self, rows: Iterable[dict]) -> None:
        if not training_authorised():
            raise NotAuthorised("detector training is not authorised (PLF1 Phase 2; C1)")
        raise NotImplementedError("the learned detector is built, not trained")  # pragma: no cover

    def score(self, snapshot: Any) -> Optional[float]:
        return None if self.weights is None else 0.0  # pragma: no cover


def learned(error_id: str, snapshot: Any) -> Optional[bool]:
    score = LearnedDetector(error_id).score(snapshot)
    return None if score is None else score >= 0.5


def register_candidates() -> None:
    """Both candidates into the shadow registry (idempotent)."""
    from services.detector_rollout import register
    register(TUNED_VERSION, tuned, stage="shadow")
    register(LEARNED_VERSION, learned, stage="shadow")


# ── the re-score job ───────────────────────────────────────────────────────

def rescore(database: Any, *, version: str, since: str, limit: int = 2000) -> dict:
    """Old clips and attempts re-scored from their stored snapshots under
    one version, into the shadow log (insert-once). Silent: it never
    touches a live verdict, a trace or a jar; the live re-score is a
    separate, founder-approved run."""
    from services.detector_rollout import ERRORS, REGISTRY, observations
    register_candidates()
    if version not in REGISTRY:
        return {"version": version, "written": 0, "error": "unknown version"}
    detector = REGISTRY[version][1]
    rows: list[dict] = []
    for clip in database.list_clips_for_rescore(since=since, limit=limit) or []:
        if not isinstance(clip, dict) or not clip.get("clip_id"):
            continue
        for row in observations(clip.get("snapshot"), clip_id=str(clip["clip_id"]),
                                take_session_id=str(clip.get("take_session_id") or ""),
                                clip_kind=str(clip.get("clip_kind") or "snippet")):
            if row["detector_version"] == version:
                rows.append(row)
    for row in rows:
        row["fired"] = bool(detector(row["error_id"], _snapshot_of(row)))
    written = int(database.record_verbal_cue_shadow(rows) or 0) if rows else 0
    return {"version": version, "since": since, "clips": len(rows) // max(1, len(ERRORS)),
            "written": written}


def _snapshot_of(row: dict) -> dict:
    measurements = row.get("measurements")
    return measurements if isinstance(measurements, dict) else {}
