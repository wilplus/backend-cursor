"""Learning-trace aggregation — backlog item 11 (developer observability).

Builds the payload behind GET /v2/admin/learning/trace: one structured view
of the TWO surviving learning lanes (shadow direction classifier,
annotation/writer corpus) so the DEVELOPER can see how coach labels and admin
annotations flow into models — stages, corpora, decision points, current
promoted models, and known gaps.

``lane_acoustic`` (the acoustic stress/charisma baseline) is GONE — founder
2026-08-03 retired stress recognition and pivoted the feature into the
peer-review validation loop. Its trainer, promote writer, runtime_config key
and admin label endpoints are all deleted. What replaces it is not a third
lane but a PROVENANCE bucket on lane_shadow: ``peer_review`` flags captured by
POST /v2/user/snippets/<id>/confidence-review (see ``_peer_review_corpus``).

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
    """Blind coach-truth corpus counts, plus the NON-BLIND peer_review bucket
    alongside them in by_selection_source.

    The peer bucket is counted here — not hidden in its own card — precisely
    because the MIX is the thing worth watching: peer flags are validations of
    the model's own predictions, so a corpus quietly drifting toward them is
    a corpus drifting toward self-agreement. It is reported from its own table
    (snippet_confidence_reviews), never merged into training_labels, and it is
    excluded from `total` — `total` means blind coach truth and must keep
    meaning that."""
    from services.db import db
    from services.confidence_reviews import SELECTION_SOURCE as _PEER_SOURCE
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
    try:
        peer_n = _count("snippet_confidence_reviews")
    except Exception as e:
        # Pre-migration / unreachable: the peer bucket is simply absent. A new
        # table must never take down the coach-corpus counts that were
        # rendering fine before it existed.
        logger.warning("learning_trace: peer_review count unavailable: %s", e)
        peer_n = 0
    if peer_n:
        by_source[_PEER_SOURCE] = peer_n
    return {
        "total": total,
        "by_class": by_class,
        "by_selection_source": by_source,
        "scanned": len(rows),
        "note": f"`total` and `by_class` are BLIND coach labels "
                f"(training_labels) only. by_selection_source additionally "
                f"carries the NON-BLIND '{_PEER_SOURCE}' bucket, read from "
                f"snippet_confidence_reviews — see lane_shadow.peer_review.",
    }


def _peer_review_corpus() -> dict:
    """The peer-review validation corpus (founder 2026-08-03) — what the
    retired acoustic stress lane became.

    Separate provenance, always: these flags are NON-BLIND (the reviewer saw
    the AI's choice before flagging), unlike the coach labels, which stay
    blind. Mixing the two indistinguishably would let the model grade its own
    homework, so the split is reported here rather than assumed."""
    from services.db import db
    from services import confidence_reviews
    rows = db.get_snippet_confidence_reviews(limit=_LABEL_SCAN_LIMIT)
    summary = confidence_reviews.review_corpus_summary(rows)
    summary["scan_capped_at"] = _LABEL_SCAN_LIMIT
    summary["counts_toward_retrain_trigger"] = \
        confidence_reviews.COUNTS_TOWARD_RETRAIN_TRIGGER
    summary["decision"] = (
        "BE 2026-08-03: peer_review rows do NOT count toward the >=50 total / "
        ">=25 new auto-retrain trigger. That trigger governs the blind "
        "coach-truth corpus; letting non-blind validations of the model's own "
        "predictions set its retrain schedule is the confirmation loop this "
        "split exists to prevent. Reversible on purpose — switching it on is "
        "one constant (confidence_reviews.COUNTS_TOWARD_RETRAIN_TRIGGER), "
        "while a model already retrained on a bad blend cannot be un-trained. "
        "How to WEIGHT peer vs. blind coach labels remains a founder call; "
        "nothing trains on this corpus yet."
    )
    return summary


def _build_lane_shadow(errors: list) -> dict:
    from services.db import db
    from services import confidence_reviews, learning_serve
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
        "peer_review": _section(
            errors, "lane_shadow.peer_review", _peer_review_corpus,
        ),
        "auto_retrain": {
            "min_total": learning_serve._RETRAIN_MIN_TOTAL,
            "new_delta": learning_serve._RETRAIN_NEW_DELTA,
            "counts_peer_review":
                confidence_reviews.COUNTS_TOWARD_RETRAIN_TRIGGER,
            "note": "fires off the label submit; result stays status=shadow — "
                    "never promoted (services/learning_serve.py). Counts BLIND "
                    "coach labels only: peer_review rows are excluded by "
                    "decision, not by accident — see lane_shadow.peer_review"
                    ".decision",
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
                {"stage": "peer-review capture (NON-BLIND, side lane)", "file": "routes/v2_routes.py:/v2/user/snippets/<id>/confidence-review → snippet_confidence_reviews"},
                {"stage": "peer_review counts toward retrain? NO", "file": "services/confidence_reviews.py:COUNTS_TOWARD_RETRAIN_TRIGGER", "decision_point": True},
            ],
            "fence": "BLIND COACH — shadow only, never promoted, never pre-fills "
                     "or surfaces a guess; frozen holdout excluded from training "
                     "(services/holdout.py). Peer-review flags are NON-BLIND and "
                     "live in their own table under their own provenance — they "
                     "never blend into the blind corpus without a founder "
                     "decision on weighting.",
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
    ],
    "retired_lanes": [
        {
            "id": "acoustic_baseline",
            "title": "Acoustic stress baseline (coach clip labels)",
            "retired_at": "2026-08-03",
            "reason": "Founder decision: stress recognition is dead. The lane "
                      "is pivoted into the peer-review validation loop — a "
                      "user/peer flags whether the AI's confidence choice was "
                      "correct (POST /v2/user/snippets/<id>/confidence-review).",
            "deleted": [
                "routes/internal_webhooks.py:internal_stress_model_train "
                "(a subprocess train pipeline inside the request handler, "
                "30-minute timeout, auto_promote defaulting to true)",
                "scripts/train_stress_classifier_baseline.py + "
                "scripts/export_stress_snippets_dataset.py — no replacement "
                "trainer",
                "runtime_config key stress_baseline_model_path and its "
                "promote writer; the local-file-path model ref with it",
                "routes/snippet_labels_routes.py + services/snippet_labels.py "
                "(/admin/snippet-labels — the lane's admin corpus writer)",
                "POST /v2/user/snippets/<id>/label (the legacy user label "
                "route) and db.set_user_snippet_charisma_label",
            ],
            "behavior_change": "Clip selection now runs on heuristic suspicion "
                               "scoring, permanently — which is exactly what "
                               "the no-model state always ran. The classifier "
                               "only ever steered SELECTION, never anything "
                               "surfaced, so nothing user-facing moved.",
            "tables_kept": "stress_snippets / snippet_labels / "
                           "charisma_snippets.user_charisma_label are LEFT IN "
                           "PLACE (no table or column is ever auto-dropped). "
                           "Nothing reads snippet_labels any more.",
        },
    ],
}

_KNOWN_GAPS = [
    {
        "id": "peer_review_weighting_undecided",
        "summary": "Peer-review flags are captured with their own provenance "
                   "(selection_source 'peer_review') but nothing trains on "
                   "them yet: whether and how heavily a NON-BLIND peer "
                   "validation should weigh against a BLIND coach label is a "
                   "founder call. The schema keeps every option open; the "
                   "retrain trigger currently ignores them entirely.",
        "file": "migrations/add_snippet_confidence_reviews.sql, "
                "services/learning_trace.py:_peer_review_corpus",
        "status": "open — decide the weight before any trainer reads this "
                  "corpus",
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
        "pipeline_docs": _PIPELINE_DOCS,
        "known_gaps": _KNOWN_GAPS,
    }
    payload["errors"] = errors
    return payload
