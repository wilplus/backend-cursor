"""Learning-trace aggregation — backlog item 11 (developer observability).

Builds the payload behind GET /v2/admin/learning/trace: one structured view
of the three learning lanes (shadow direction classifier, annotation/writer
corpus, acoustic stress/charisma baseline) so the DEVELOPER can see how coach
labels and admin annotations flow into models — stages, corpora, decision
points, current promoted models, and known gaps.

ADMIN-ONLY surface (BLIND COACH: the shadow lane exposes machine guesses vs
coach labels — a coach must never see this; AC-9/CONSTRUCT: nothing here is
ever user-facing). Content spec: docs/ENGINE-MAP.md §2–4 + PHASE-A0-FINDINGS.md;
reader guide: docs/LEARNING-TRACE.md.

Every section is built defensively: a failing section becomes null and an
entry in errors[] — the page always renders whatever is reachable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_EVENT_SCAN_LIMIT = 10000       # admin_annotation_events rows scanned for totals
_LABEL_SCAN_LIMIT = 20000       # training_labels rows scanned for class counts
_SHADOW_SCAN_LIMIT = 2000       # shadow_predictions rows for agreement-over-time
_EXPORT_RUNS_LIMIT = 10


def _section(errors: list, name: str, fn: Callable[[], Any]) -> Any:
    """Run one section builder; on failure record the error and return None."""
    try:
        return fn()
    except Exception as e:  # defensive by design — the trace must render
        logger.warning("learning_trace: section %s failed: %s", name, e)
        errors.append({"section": name, "error": str(e)[:500]})
        return None


def _count(table: str, **eq_filters) -> int:
    from services.db import db
    q = db.client.table(table).select("id", count="exact")
    for k, v in eq_filters.items():
        q = q.eq(k, v)
    res = q.limit(1).execute()
    return int(getattr(res, "count", None) or 0)


def _runtime_config_row(key: str) -> Optional[dict]:
    """Full runtime_config row (value + metadata + provenance), or None."""
    from services.db import db
    res = (
        db.client.table("runtime_config")
        .select("key, value, updated_at, updated_by, metadata")
        .eq("key", key)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def _iso_week(ts: Any) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return None


# ── lane_shadow — coach direction labels → shadow logistic regression ──────

def _shadow_coefficients() -> Optional[dict]:
    """Logistic-regression coefficients per named feature from the latest
    joblib artifact (the 11 features pinned in services/learning_export.py).
    Coefficients are on STANDARDIZED features (StandardScaler), so |weight|
    is comparable across features. None when no artifact is loadable —
    the caller then shows metrics-only."""
    from services.learning_serve import _latest_bundle
    from services.learning_export import FEATURES_11

    version, bundle = _latest_bundle()
    if not bundle:
        return None
    pipe = bundle.get("pipeline")
    if pipe is None:
        return None
    clf = getattr(pipe, "named_steps", {}).get("clf")
    if clf is None or not hasattr(clf, "coef_"):
        return None
    features = list(bundle.get("features") or FEATURES_11)
    classes = [str(c) for c in getattr(clf, "classes_", [])]
    coef = clf.coef_  # (1, n) binary — row maps to classes_[1]; (k, n) multi
    per_feature = []
    for i, name in enumerate(features):
        weights = {}
        if coef.shape[0] == 1 and len(classes) == 2:
            weights[classes[1]] = round(float(coef[0][i]), 5)
        else:
            for ci, cname in enumerate(classes):
                weights[cname] = round(float(coef[ci][i]), 5)
        per_feature.append({
            "feature": name,
            "weights": weights,
            "weight_abs_max": round(max(abs(w) for w in weights.values()), 5)
            if weights else 0.0,
        })
    intercept = [round(float(b), 5) for b in getattr(clf, "intercept_", [])]
    return {
        "model_version": version,
        "classes": classes,
        "per_feature": per_feature,
        "intercept": intercept,
        "note": "weights are on standardized (z-scored) features; "
                "binary weights point toward classes[1]",
    }


def _shadow_agreement_over_time() -> Optional[list]:
    """Weekly agreement buckets from shadow_predictions (capped query)."""
    from services.db import db
    res = (
        db.client.table("shadow_predictions")
        .select("created_at, predicted_label, coach_actual_label")
        .not_.is_("coach_actual_label", "null")
        .order("created_at", desc=True)
        .limit(_SHADOW_SCAN_LIMIT)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return None
    buckets: dict = {}
    for r in rows:
        wk = _iso_week(r.get("created_at"))
        if not wk:
            continue
        hit, tot = buckets.get(wk, (0, 0))
        agree = 1 if r.get("predicted_label") == r.get("coach_actual_label") else 0
        buckets[wk] = (hit + agree, tot + 1)
    return [
        {"week": wk, "agreement": round(h / t, 4), "n": t}
        for wk, (h, t) in sorted(buckets.items())
        if t
    ]


def _training_label_counts() -> dict:
    from services.db import db
    total = db.count_training_labels()
    res = (
        db.client.table("training_labels")
        .select("value, selection_source")
        .limit(_LABEL_SCAN_LIMIT)
        .execute()
    )
    rows = res.data or []
    by_class: dict = {}
    by_source: dict = {}
    for r in rows:
        v = r.get("value") or "(null)"
        s = r.get("selection_source") or "heuristic"
        by_class[v] = by_class.get(v, 0) + 1
        by_source[s] = by_source.get(s, 0) + 1
    return {
        "total": total,
        "by_class": by_class,
        "by_selection_source": by_source,
        "scanned": len(rows),
    }


def _build_lane_shadow(errors: list) -> dict:
    from services.db import db
    from services import learning_serve
    return {
        "model_versions": _section(
            errors, "lane_shadow.model_versions",
            lambda: db.list_model_versions(limit=20),
        ),
        "coefficients": _section(
            errors, "lane_shadow.coefficients", _shadow_coefficients,
        ),
        "shadow_agreement": _section(
            errors, "lane_shadow.shadow_agreement", db.get_shadow_agreement,
        ),
        "agreement_over_time": _section(
            errors, "lane_shadow.agreement_over_time",
            _shadow_agreement_over_time,
        ),
        "training_labels": _section(
            errors, "lane_shadow.training_labels", _training_label_counts,
        ),
        "auto_retrain": {
            "min_total": learning_serve._RETRAIN_MIN_TOTAL,
            "new_delta": learning_serve._RETRAIN_NEW_DELTA,
            "note": "fires off the label submit; result stays status=shadow — "
                    "never promoted (services/learning_serve.py)",
        },
    }


# ── lane_annotations — admin/coach text edits → SFT/DPO → copilot model ────

def _annotation_event_totals() -> dict:
    from services.db import db
    res = (
        db.client.table("admin_annotation_events")
        .select("section_type, field_name, reason_chip, "
                "previous_value_hash, new_value_hash")
        .order("created_at", desc=True)
        .limit(_EVENT_SCAN_LIMIT)
        .execute()
    )
    rows = res.data or []
    by_section: dict = {}
    by_field: dict = {}
    by_chip: dict = {}
    approved = overridden = undetermined = 0
    for r in rows:
        st = r.get("section_type") or "(null)"
        fn = r.get("field_name") or "(null)"
        ch = r.get("reason_chip") or "(none)"
        by_section[st] = by_section.get(st, 0) + 1
        by_field[fn] = by_field.get(fn, 0) + 1
        by_chip[ch] = by_chip.get(ch, 0) + 1
        prev_h, new_h = r.get("previous_value_hash"), r.get("new_value_hash")
        if prev_h and new_h:
            if prev_h == new_h:
                approved += 1
            else:
                overridden += 1
        else:
            undetermined += 1
    return {
        "total": len(rows),
        "by_section_type": by_section,
        "by_field_name": by_field,
        "by_reason_chip": by_chip,
        "approve_vs_override": {
            "approved_verbatim": approved,
            "overridden": overridden,
            "undetermined_no_hashes": undetermined,
            "note": "derived from previous/new value hashes; rows without "
                    "hashes can't be classified",
        },
        "scan_capped_at": _EVENT_SCAN_LIMIT,
    }


def _annotation_export_runs() -> list:
    from services.db import db
    res = (
        db.client.table("admin_annotation_export_runs")
        .select("id, started_at, ended_at, status, processed_count, "
                "exported_count, failed_count, export_uri, created_by, "
                "checkpoint_created_at, error_text")
        .order("started_at", desc=True)
        .limit(_EXPORT_RUNS_LIMIT)
        .execute()
    )
    return res.data or []


def _build_lane_annotations(errors: list) -> dict:
    return {
        "annotation_events": _section(
            errors, "lane_annotations.annotation_events",
            _annotation_event_totals,
        ),
        "export_runs": _section(
            errors, "lane_annotations.export_runs", _annotation_export_runs,
        ),
        "copilot_model": _section(
            errors, "lane_annotations.copilot_model",
            lambda: _runtime_config_row("openai_copilot_model"),
        ),
    }


# ── lane_acoustic — coach clip labels → baseline stress classifier ─────────

def _snippet_label_counts(table: str, positive: str, negative: str) -> dict:
    return {
        "total": _count(table),
        "labeled_" + positive: _count(table, coach_label=positive),
        "labeled_" + negative: _count(table, coach_label=negative),
    }


def _snippet_labels_stats() -> dict:
    """Multi-labeler snippet_labels table (routes/snippet_labels_routes.py
    stats twin, without the per-admin split)."""
    from services.db import db
    total = _count("snippet_labels")
    high = (
        db.client.table("snippet_labels")
        .select("id", count="exact").eq("confidence", "high").limit(1).execute()
    )
    low = (
        db.client.table("snippet_labels")
        .select("id", count="exact").eq("confidence", "low").limit(1).execute()
    )
    return {
        "labels_total": total,
        "confidence_high": int(getattr(high, "count", None) or 0),
        "confidence_low": int(getattr(low, "count", None) or 0),
    }


def _build_lane_acoustic(errors: list) -> dict:
    return {
        "stress_snippets": _section(
            errors, "lane_acoustic.stress_snippets",
            lambda: _snippet_label_counts("stress_snippets", "stress", "no_stress"),
        ),
        "charisma_snippets": _section(
            errors, "lane_acoustic.charisma_snippets",
            lambda: _snippet_label_counts("charisma_snippets", "charisma", "no_charisma"),
        ),
        "stress_baseline_model": _section(
            errors, "lane_acoustic.stress_baseline_model",
            lambda: _runtime_config_row("stress_baseline_model_path"),
        ),
        "snippet_labels": _section(
            errors, "lane_acoustic.snippet_labels", _snippet_labels_stats,
        ),
    }


# ── static pipeline description + known gaps (spec: ENGINE-MAP.md §2–4) ────

_PIPELINE_DOCS = {
    "source": "docs/ENGINE-MAP.md §2–3; decision-point verdicts from "
              "PHASE-A0-FINDINGS.md (A3.4) — see docs/LEARNING-TRACE.md",
    "lanes": [
        {
            "id": "shadow_direction",
            "title": "Shadow direction classifier (coach voice labels)",
            "corpus": "training_labels ⋈ charisma_snippets.metrics (the 11 "
                      "acoustic features, services/learning_export.py:FEATURES_11)",
            "stages": [
                {"stage": "coach labels (blind)", "file": "services/training_labels.py → db.upsert_training_labels"},
                {"stage": "export JSONL", "file": "services/learning_export.py"},
                {"stage": "auto-retrain @ ≥50 total / ≥25 new", "file": "services/learning_serve.py:maybe_auto_retrain", "decision_point": True},
                {"stage": "fit logistic regression", "file": "services/learning_train.py"},
                {"stage": "shadow predict + agreement log", "file": "services/learning_serve.py → shadow_predictions"},
            ],
            "fence": "BLIND COACH — shadow only, never promoted, never pre-fills "
                     "or surfaces a guess; frozen holdout excluded from training "
                     "(services/holdout.py)",
        },
        {
            "id": "annotation_writer",
            "title": "Annotation → writer models (copilot SFT/DPO)",
            "corpus": "admin_annotation_events (AI draft vs coach final text pairs)",
            "stages": [
                {"stage": "publish/keep/verify capture", "file": "admin_annotation_events (migrations/add_admin_copilot_foundation.sql)"},
                {"stage": "JSONL export (cron/webhook)", "file": "services/annotation_export.py + routes/internal_webhooks.py:/v2/internal/annotation-export"},
                {"stage": "SFT / DPO exports (CLI only)", "file": "scripts/export_openai_finetuning_jsonl.py, scripts/export_openai_preference_jsonl.py"},
                {"stage": "manual promote", "file": "scripts/promote_openai_model.py → runtime_config openai_copilot_model", "decision_point": True},
                {"stage": "serve", "file": "services/openai_service.py (purpose=copilot)"},
            ],
            "fence": "human-gated promote (PHASE-A0 A3.4); text lane — no scores",
        },
        {
            "id": "acoustic_baseline",
            "title": "Acoustic stress baseline (coach clip labels)",
            "corpus": "stress_snippets / charisma_snippets coach_label + snippet_labels",
            "stages": [
                {"stage": "clip generation + coach label", "file": "services/stress_snippet_service.py, routes/snippet_labels_routes.py"},
                {"stage": "dataset export", "file": "scripts/export_stress_snippets_dataset.py"},
                {"stage": "train (17-feature logreg)", "file": "scripts/train_stress_classifier_baseline.py"},
                {"stage": "quality gate (recall/precision/FPR targets)", "file": "scripts/train_stress_classifier_baseline.py quality_gate", "decision_point": True},
                {"stage": "gate-guarded promote → runtime_config", "file": "routes/internal_webhooks.py:internal_stress_model_train", "decision_point": True},
                {"stage": "serve (clip selection only)", "file": "services/stress_snippet_service.py:_load_baseline_model"},
            ],
            "fence": "AC-9/CONSTRUCT — classifier steers clip SELECTION for coach "
                     "labeling only; probability never surfaced",
        },
    ],
}

_KNOWN_GAPS = [
    {
        "id": "charisma_uses_stress_model",
        "summary": "charisma_snippet_service ranks charisma clips with the STRESS "
                   "classifier — _load_baseline_model() hardcodes "
                   "stress_baseline_model_path; no charisma model key exists.",
        "file": "services/charisma_snippet_service.py:~100",
        "status": "flagged only — behavior unchanged; a charisma-specific model "
                  "is a product/ML (founder) decision",
    },
    {
        "id": "dpo_sft_exports_cli_only",
        "summary": "SFT/DPO fine-tuning exports and copilot model promotion are "
                   "CLI scripts only (no endpoint, no cron).",
        "file": "scripts/export_openai_finetuning_jsonl.py, "
                "scripts/export_openai_preference_jsonl.py, "
                "scripts/promote_openai_model.py",
        "status": "by design so far (human-gated), but invisible without this page",
    },
    {
        "id": "no_annotation_model_lineage",
        "summary": "No lineage table links annotation events/exports to the model "
                   "trained from them — provenance is by timestamp convention only.",
        "file": "admin_annotation_export_runs (closest ledger)",
        "status": "open",
    },
    {
        "id": "phase_a0_corpus_verdicts",
        "summary": "PHASE-A0-FINDINGS.md (2026-05-16) verdicts: fine-tune corpus "
                   "NOT VIABLE (admin_annotation_events was empty), few-shot loop "
                   "starved. Not recomputed live — re-run "
                   "scripts/phase_a0_diagnostics.py for a fresh read.",
        "file": "PHASE-A0-FINDINGS.md",
        "status": "stale snapshot — see lane_annotations totals for current counts",
    },
]


def build_learning_trace() -> dict:
    """Assemble the full admin-only learning trace payload."""
    errors: list = []
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audience": "developer/admin only — BLIND COACH + AC-9 fenced; "
                    "never surface any of this to users or coaches",
        "lane_shadow": _section(
            errors, "lane_shadow", lambda: _build_lane_shadow(errors),
        ),
        "lane_annotations": _section(
            errors, "lane_annotations", lambda: _build_lane_annotations(errors),
        ),
        "lane_acoustic": _section(
            errors, "lane_acoustic", lambda: _build_lane_acoustic(errors),
        ),
        "pipeline_docs": _PIPELINE_DOCS,
        "known_gaps": _KNOWN_GAPS,
    }
    payload["errors"] = errors
    return payload
