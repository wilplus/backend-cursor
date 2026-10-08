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
  * ``learned-v1``: a per-error model on snapshot features, fitted on our
    own systems from the blind-check answers of speakers who hold the
    training yes and have not objected (3.5 pack, file 22 E3; 02 v1.2 §3c).
    ``fit`` refuses while Config.DETECTOR_TRAINING_AUTHORISED is False; the
    weekly learning job (``fit_all``) is its only caller, and a fit's
    verdicts go only to the shadow log under ``learned-v1+<digest>``.

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


#: The fit's own version: a change to the method below is a new one.
FIT_METHOD = "weighted-stump-v1"
#: Below this many Yes AND this many No answers for an error, nothing is
#: fitted (the report card's own floor, error_presence_audit.MIN_PER_BOX).
FIT_MIN_PER_CLASS = 30
#: The shadow re-score after a fit reads this far back.
FIT_SHADOW_DAYS = 28


class LearnedDetector:
    """A per-error model on snapshot features, fitted on our own systems
    (3.5 pack, file 22 E3; document 02 v1.2 §3c): plain Python, no
    third-party model and no provider. ``fit`` refuses while
    Config.DETECTOR_TRAINING_AUTHORISED is False.

    The model is the smallest one that can be graded: one feature, one
    direction, one cut-off (a weighted decision stump), chosen to maximise
    the balanced accuracy of the coaches' blind Yes/No answers, each answer
    weighted by the inverse of its sampling probability. Deterministic: the
    same answers give the same cut-off and the same ``fit_version``.

    SHADOW ONLY. A fitted detector's verdict is written to the shadow log
    under its own version (``serves_user`` is false by the table's check);
    nothing serves it, nothing promotes it (LIVE_DETECTOR is a reviewed
    line), and its verdict stays its own provenance (L3)."""

    FEATURES = ("wpm", "pause_ratio", "pause_regularity", "median_gap", "tight_gap_share",
                "word_occupancy", "word_recognition_confidence", "ending_duration_ratio")

    def __init__(self, error_id: str) -> None:
        self.error_id = error_id
        self.model: Optional[dict] = None

    def fit(self, rows: Iterable[dict]) -> dict:
        """Fit on answered blind-check rows that the caller has already
        limited to speakers who hold the training yes (``training_rows``).
        Returns the fit result; ``model`` is set only when one was fitted."""
        if not training_authorised():
            raise NotAuthorised("detector training is not authorised (PLF1 Phase 2; C1)")
        data = _examples(rows, self.error_id, self.FEATURES)
        n_yes = sum(1 for _, y, _ in data if y)
        n_no = len(data) - n_yes
        result: dict = {"error_id": self.error_id, "method": FIT_METHOD,
                        "n_yes": n_yes, "n_no": n_no,
                        "data_sha256": _digest([[sorted(f.items()), y, w] for f, y, w in data])}
        if n_yes < FIT_MIN_PER_CLASS or n_no < FIT_MIN_PER_CLASS:
            self.model = None
            return {**result, "fitted": False, "why": "not enough answers yet"}
        best = _best_stump(data, self.FEATURES)
        if best is None:
            self.model = None
            return {**result, "fitted": False, "why": "no feature separates the answers"}
        model = {"feature": best[0], "direction": best[1], "cut": best[2]}
        version = f"{LEARNED_VERSION}+{_digest([FIT_METHOD, self.error_id, model, result['data_sha256']])[:12]}"
        self.model = {**model, "fit_version": version}
        return {**result, "fitted": True, "fit_version": version, "model": model,
                "balanced_accuracy": round(best[3], 4)}

    def score(self, snapshot: Any) -> Optional[float]:
        """1.0 fired, 0.0 quiet, None with no model or no measurement."""
        if self.model is None:
            return None
        value = _num(snapshot if isinstance(snapshot, dict) else {}, self.model["feature"])
        if value is None:
            return None
        cut = float(self.model["cut"])
        fired = value < cut if self.model["direction"] == "lt" else value > cut
        return 1.0 if fired else 0.0


def learned(error_id: str, snapshot: Any) -> Optional[bool]:
    """The registered learned candidate: no model is loaded into a serving
    process, so it answers None. A fit's verdicts reach the shadow log only
    through ``fit_all`` under the fit's own version."""
    score = LearnedDetector(error_id).score(snapshot)
    return None if score is None else score >= 0.5


def _digest(value: Any) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def _examples(rows: Iterable[dict], error_id: str,
              features: tuple[str, ...]) -> list[tuple[dict, bool, float]]:
    """(features, said yes, weight) per answered row of this error, in a
    fixed order. Can't-tell answers and rows with nothing measured are left
    out; the weight is 1 / sampling probability (1 when none is stored)."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or str(r.get("error_id")) != error_id \
                or r.get("answer") not in ("yes", "no"):
            continue
        raw = r.get("measurements")
        measured: dict = raw if isinstance(raw, dict) else {}
        feats: dict[str, float] = {}
        for k in features:
            value = _num(measured, k)
            if value is not None:
                feats[k] = value
        if not feats:
            continue
        p = r.get("sampling_probability")
        weight = 1.0 / float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) \
            and 0 < float(p) <= 1 else 1.0
        out.append((str(r.get("clip_id") or ""), str(r.get("coach_id") or ""),
                    feats, r["answer"] == "yes", weight))
    out.sort(key=lambda t: (t[0], t[1], t[3]))
    return [(f, y, w) for _, _, f, y, w in out]


def _best_stump(data: list[tuple[dict, bool, float]],
                features: tuple[str, ...]) -> Optional[tuple[str, str, float, float]]:
    """(feature, 'lt'|'gt', cut, balanced accuracy) maximising the weighted
    balanced accuracy over every midpoint cut of every feature. Ties keep
    the first in feature order, then 'lt' before 'gt', then the lower cut,
    so the answer never depends on row order. None when no cut beats 0.5."""
    best: Optional[tuple[str, str, float, float]] = None
    for feature in features:
        points = sorted((f[feature], y, w) for f, y, w in data if feature in f)
        total_yes = sum(w for _, y, w in points if y)
        total_no = sum(w for _, y, w in points if not y)
        if total_yes <= 0 or total_no <= 0:
            continue
        below_yes = below_no = 0.0
        for i in range(len(points) - 1):
            value, y, w = points[i]
            if y:
                below_yes += w
            else:
                below_no += w
            nxt = points[i + 1][0]
            if nxt == value:
                continue
            cut = round((value + nxt) / 2.0, 6)
            # 'lt' fires below the cut: caught = yes below, quiet = no above.
            lt = 0.5 * (below_yes / total_yes + (total_no - below_no) / total_no)
            for direction, score in (("lt", lt), ("gt", 1.0 - lt)):
                if score > 0.5 and (best is None or score > best[3] + 1e-12):
                    best = (feature, direction, cut, score)
    return best


def _fit_take_ok(database: Any, take_session_id: str) -> bool:
    """3.5 E3: a Take's answers train a detector only while its speaker
    holds the training yes and has not objected to the blind check (an
    objection that cannot be read counts as one). The two existing reads,
    composed; no rule of its own."""
    from services.error_presence_audit import _objected
    from services.pair_consent import take_holds_training_yes
    if not take_session_id or not take_holds_training_yes(database, take_session_id):
        return False
    return not _objected(database, take_session_id)


def training_rows(database: Any, *, split_of: Any = None) -> list[dict]:
    """The blind-check answers a fit may use: answered Yes or No, from a
    speaker who holds the training yes and has not objected (read NOW,
    so a withdrawal drops out at the next fit), and from the fair test's
    TRAIN split only, so the held-out speakers it grades on stay unseen."""
    if split_of is None:
        from services.exercise_fair_test import split_of
    ok: dict[str, bool] = {}
    out = []
    for r in database.list_error_presence_audit_answered_all() or []:
        if not isinstance(r, dict) or r.get("answer") not in ("yes", "no"):
            continue
        if split_of(str(r.get("speaker_user_id") or "")) != "train":
            continue
        take = str(r.get("take_session_id") or "")
        if take not in ok:
            ok[take] = _fit_take_ok(database, take)
        if ok[take]:
            out.append(r)
    return out


def fit_all(database: Any, *, config: Any = None, now: Any = None) -> dict:
    """The weekly learning job's detector step (3.5 E3). Off: nothing is
    read and nothing is written. On: each error is fitted on the consented
    answers, and each fitted detector's verdicts on recent clips of
    consented speakers go into the shadow log under the fit's own version
    (insert-once, so an unchanged fit writes nothing new). Returns the fit
    results, which the job keeps in the week's snapshot: aggregate counts
    and a cut-off, never an id or a person (AC-9)."""
    from datetime import datetime, timedelta, timezone
    if config is None:
        from config import Config as config
    if not bool(getattr(config, "DETECTOR_TRAINING_AUTHORISED", False)) or not training_authorised():
        return {"skipped": "DETECTOR_TRAINING_AUTHORISED is off"}
    from services.detector_rollout import ERRORS
    rows = training_rows(database)
    fits: dict[str, dict] = {}
    fitted: dict[str, LearnedDetector] = {}
    for error_id in ERRORS:
        detector = LearnedDetector(error_id)
        fits[error_id] = detector.fit(rows)
        if detector.model is not None:
            fitted[error_id] = detector
    moment = now or datetime.now(timezone.utc)
    since = (moment - timedelta(days=FIT_SHADOW_DAYS)).isoformat()
    written = _shadow_score(database, fitted, since=since) if fitted else 0
    return {"method": FIT_METHOD, "fits": fits, "shadow_written": written}


def _shadow_score(database: Any, fitted: dict[str, "LearnedDetector"], *, since: str) -> int:
    """The fitted detectors' verdicts on recent clips of consented speakers,
    into the shadow log under each fit's own version. Insert-once."""
    ok: dict[str, bool] = {}
    rows: list[dict] = []
    for clip in database.list_clips_for_rescore(since=since) or []:
        if not isinstance(clip, dict) or not clip.get("clip_id"):
            continue
        take = str(clip.get("take_session_id") or "")
        if take not in ok:
            ok[take] = _fit_take_ok(database, take)
        if not ok[take]:
            continue
        raw = clip.get("snapshot")
        snapshot: dict = raw if isinstance(raw, dict) else {}
        measurements = {k: snapshot[k] for k in LearnedDetector.FEATURES
                        if _num(snapshot, k) is not None}
        for error_id in sorted(fitted):
            detector = fitted[error_id]
            score = detector.score(snapshot)
            if score is None or detector.model is None:
                continue
            rows.append({
                "take_session_id": take, "snippet_id": str(clip["clip_id"]),
                "recording_id": None, "error_id": error_id,
                "detector_version": str(detector.model["fit_version"]),
                "language": "any", "fired": score >= 0.5, "measurements": measurements,
                "clip_kind": str(clip.get("clip_kind") or "snippet"),
            })
    return int(database.record_verbal_cue_shadow(rows) or 0) if rows else 0


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
