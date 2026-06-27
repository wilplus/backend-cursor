"""Snippet-labels dataset export (willab Phase 4 / Prompt 1, B1).

Joins training_labels (direction-v1: the coach's per-snippet direction label)
with charisma_snippets.metrics (the 11 acoustic features) into versioned JSONL
rows — the corpus the SHADOW direction classifier trains on. Read-only,
idempotent, and it emits a class-balance summary so a caller can see whether
the corpus is usable (and §7's "features missing on snippets" integrity case).

The model influences NOTHING; this is just the capture→export half of the
loop. build_export_rows is pure (DB-free) so it's unit-tested directly.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from services.holdout import is_holdout

logger = logging.getLogger(__name__)

# The 11 acoustic features (the raw metric keys on charisma_snippets.metrics).
FEATURES_11 = (
    "f0_mean", "f0_sd", "f0_slope", "f0_mid_end_delta", "wpm",
    "pause_ms", "pause_ratio", "pause_regularity", "dynamic_db",
    "intensity_envelope", "voiced_ratio",
)


def _extract_features(metrics: Any) -> Optional[dict]:
    """Pull the 11 features off a metrics dict. Returns the (possibly partial)
    dict of present numeric features, or None when metrics isn't a dict."""
    if not isinstance(metrics, dict):
        return None
    feats: dict = {}
    for k in FEATURES_11:
        v = metrics.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            feats[k] = float(v)
    return feats


def build_export_rows(
    labels: list[dict], metrics_by_snippet: dict,
    data_origin_by_snippet: Optional[dict] = None,
) -> tuple[list[dict], dict]:
    """Pure join: (labels, {snippet_id: metrics}) → (rows, summary).

    A label is DROPPED (not exported) when its snippet has no metrics or an
    incomplete 11-feature vector — that's the §7 integrity signal, surfaced in
    summary.dropped_no_features rather than emitting junk rows.

    SUBSYSTEM-S WALL: this is the coach-TRUTH corpus. Any snippet whose
    ``data_origin`` is ``'synthetic'`` is HARD-EXCLUDED (counted in
    summary.dropped_synthetic) so generated data can never contaminate the truth
    set or, downstream, a validation/holdout drawn from it. ``data_origin_by_
    snippet`` is optional + defaults to {} → no exclusion, so existing callers
    and tests are unaffected until provenance is populated.
    """
    origin = data_origin_by_snippet or {}
    rows: list[dict] = []
    by_class: dict = {}
    dropped = 0
    dropped_synthetic = 0
    for lab in (labels or []):
        sid = lab.get("snippet_id")
        value = lab.get("value")
        if not sid or not value:
            dropped += 1
            continue
        if origin.get(sid) == "synthetic":
            dropped_synthetic += 1
            continue
        feats = _extract_features(metrics_by_snippet.get(sid))
        if not feats or len(feats) < len(FEATURES_11):
            dropped += 1
            continue
        rows.append({
            "snippet_id": sid,
            "session_id": lab.get("session_id"),
            "features": feats,
            "label": value,
            "schema_version": lab.get("schema_version"),
            "was_pre_filled": bool(lab.get("was_pre_filled")),
            "was_overridden": bool(lab.get("was_overridden")),
            "selection_source": lab.get("selection_source") or "heuristic",
            "labeled_at": lab.get("labeled_at"),
            # Readiness rig #3: the FROZEN holdout bit (deterministic in
            # snippet_id). Training EXCLUDES these; the eval scores ONLY these,
            # so machine-vs-coach agreement is uncontaminated.
            "is_holdout": is_holdout(sid),
        })
        by_class[value] = by_class.get(value, 0) + 1
    summary = {
        "total": len(rows),
        "by_class": by_class,
        "dropped_no_features": dropped,
        "dropped_synthetic": dropped_synthetic,
        "holdout": sum(1 for r in rows if r.get("is_holdout")),
        "feature_count": len(FEATURES_11),
        "coaches": len({
            r["session_id"] for r in rows if r.get("session_id")
        }) or None,
    }
    return rows, summary


def export_snippet_labels_dataset() -> tuple[list[dict], dict]:
    """DB-backed export: all training_labels ⋈ their snippet features.

    Subsystem-S wall: fetches each snippet's data_origin too, so synthetic rows
    are hard-excluded from the truth corpus (build_export_rows). Pre-migration /
    missing column → empty origin map → no exclusion (there is no synthetic data
    yet anyway)."""
    from services.db import db
    labels = db.get_all_training_labels() or []
    sids = [l.get("snippet_id") for l in labels if l.get("snippet_id")]
    metrics = db.get_snippet_metrics_by_ids(sids) or {}
    origins = db.get_snippet_data_origin_by_ids(sids) or {}
    return build_export_rows(labels, metrics, origins)


def write_jsonl(rows: list[dict], path: str) -> int:
    """Write rows as JSONL. Returns the count written."""
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n
