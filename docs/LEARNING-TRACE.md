# LEARNING-TRACE — the developer window into the learning lanes

**Backlog item 11** ("for the developer to understand the architecture") —
developer observability for the F1/F2 learning loop. Admin-only; fences
**AC-9 / CONSTRUCT / BLIND COACH** apply in full: nothing on this surface is
ever shown to a user or a coach.

- **Endpoint:** `GET /v2/admin/learning/trace` (`routes/v2_routes.py`,
  `@require_admin` — deliberately NOT `@require_admin_or_coach` like the
  sibling `/v2/admin/learning/*` endpoints: the payload shows machine guesses
  next to coach labels, which BLIND COACH forbids a coach from seeing).
- **Aggregation:** `services/learning_trace.py` — every section is built in
  its own try/except; a broken corpus becomes `null` plus an entry in
  `errors[]`, never a 500.
- **Page:** frontend `/admin/learning` (not linked in nav), BFF proxy at
  `src/app/api/v2/admin/learning/trace/route.ts` forwarding the Supabase JWT.
  Components: `src/components/admin/LearningTraceView.tsx`.

Content spec is **`docs/ENGINE-MAP.md` §2–4** (corpora, loop diagram, future
models) and **`PHASE-A0-FINDINGS.md`** (the human-gated-promote decision,
A3.4). This document only explains how to *read* the page — it does not
duplicate the engine map.

## How to read the page

Top to bottom: **Pipelines** (the three stage-flows; orange badges mark
decision points), then one card per lane with its live numbers, then
**Known gaps**. A yellow banner at the top lists any sections that failed to
load — the rest of the page still renders.

## The three lanes

### Lane 1 — shadow direction classifier (coach voice labels)

`coach label (blind) → export → auto-retrain trigger → fit → shadow predict`

- Corpus: `training_labels` ⋈ `charisma_snippets.metrics` — the **11 acoustic
  features** pinned in `services/learning_export.py:23-27` (`FEATURES_11`).
- Train: `services/learning_train.py:32` (`train_direction_classifier`,
  sklearn logistic regression; frozen holdout excluded via
  `services/holdout.py`). Registry: `model_versions`
  (`services/db.py:12808`).
- **Decision point (auto-retrain):** `services/learning_serve.py:134`
  (`maybe_auto_retrain`) — ≥50 total labels AND ≥25 new since the last model.
  The result stays `status=shadow`; **it is never promoted** and never
  pre-fills anything.
- Agreement: `shadow_predictions` predicted-vs-coach
  (`services/db.py:12921`, `get_shadow_agreement`) — in-distribution,
  labelled as such on the page. The weekly sparkline groups the same rows by
  ISO week.
- The **coefficients table** (from the latest joblib artifact, weights on
  standardized features, sorted by |w|) is the direct answer to "how do the
  coach's annotations shape the model's understanding of acoustics".

### Lane 2 — annotations → writer models (copilot SFT/DPO)

`publish/keep/verify capture → JSONL export → SFT/DPO export (CLI) → manual promote → serve`

- Corpus: `admin_annotation_events` (AI draft vs coach final text pairs;
  schema in `migrations/add_admin_copilot_foundation.sql:104`).
  Approve-vs-override on the page is derived from the value hashes
  (equal ⇒ approved verbatim); rows without hashes are "undetermined".
- Export ledger: `admin_annotation_export_runs`
  (`services/annotation_export.py`), fed by cron/webhook
  `routes/internal_webhooks.py` `/v2/internal/annotation-export`.
- **Decision point (human promote):** `scripts/promote_openai_model.py` →
  `runtime_config.openai_copilot_model`, read by
  `services/openai_service.py:178`. No automation — PHASE-A0 A3.4.

### Lane 3 — acoustic stress baseline (coach clip labels)

`clip generation + coach label → dataset export → train (17 features) → quality gate → gate-guarded promote → serve`

- Corpora: `stress_snippets` / `charisma_snippets` `coach_label`, plus the
  multi-labeler `snippet_labels` table (`routes/snippet_labels_routes.py`).
- Train: `scripts/train_stress_classifier_baseline.py`; serving twin:
  `services/stress_snippet_service.py:672` (`_feature_vector_for_model`).
- **Decision point (quality gate):** the trainer computes `quality_gate`
  (recall/precision/FPR targets) into the metrics file and the artifact.
- **Decision point (promote):** `routes/internal_webhooks.py`
  `internal_stress_model_train` promotes
  `runtime_config.stress_baseline_model_path` — now **gate-guarded** (see
  fixes below). The promotion metadata records the gate outcome and any
  force flag, and the page shows them.
- Serving: the classifier only steers which clips get offered for coach
  labeling (selection/uncertainty). The probability is never surfaced
  (AC-9 / CONSTRUCT).

## The two fixes shipped with this page (2026-07-30)

1. **16-vs-17 feature-vector training/serving skew** —
   `scripts/train_stress_classifier_baseline.py` returned a 16-dim zero
   vector on the empty-frame path while the populated path and the serving
   twin (`services/stress_snippet_service.py:681`) are 17-dim. Fixed with a
   module-level `FEATURE_NAMES` (17 names, serving order) as the single
   source of truth: the zeros path returns `len(FEATURE_NAMES)` and the
   artifact's `feature_names` derives from it. Test:
   `test_learning_trace.py::StressTrainerFeatureParityTests`.

2. **Quality gate not enforced on auto-promote** — the train webhook passed
   gate thresholds to the trainer but never read the result;
   `auto_promote` (default true) promoted gate-failing models, and on a
   storage-upload failure it promoted a **local ephemeral path** unreadable
   on other dynos. Now (`routes/internal_webhooks.py`
   `internal_stress_model_train`):
   - gate failed or missing → **no promote**, response
     `promoted:false` + `promotion_skipped_reason:
     "quality_gate_failed" | "quality_gate_missing"` + the gate details;
   - explicit `force_promote:true` overrides the gate (logged loudly,
     recorded in the runtime_config metadata);
   - storage upload failed → **never promote**
     (`promotion_skipped_reason:"artifact_not_in_storage"`) —
     `force_promote` does NOT override this;
   - the promotion metadata blob records `quality_gate`,
     `quality_gate_ok`, `force_promote`, `promoted_via`.
   `auto_promote` still defaults to true, but is gate-guarded — this is what
   PHASE-A0's "Promote stays human-gated (A3.4)" means in practice: passing
   models may still auto-promote; failing models cannot slip through without
   an explicit human `force_promote`. Tests:
   `test_learning_trace.py::StressModelTrainWebhookGateTests`.

## Known gaps (surfaced in the payload's `known_gaps`)

- **`charisma_uses_stress_model`** — `services/charisma_snippet_service.py`
  (~line 100) ranks charisma clips with the STRESS classifier
  (`_load_baseline_model` hardcodes `stress_baseline_model_path`; no
  charisma model key exists). Flagged in code + here; behavior deliberately
  unchanged — a charisma-specific model is a product/ML (founder) decision.
- **`dpo_sft_exports_cli_only`** — writer-model exports and copilot
  promotion are CLI scripts only.
- **`no_annotation_model_lineage`** — nothing links annotation
  events/exports to the model trained from them.
- **`phase_a0_corpus_verdicts`** — the PHASE-A0 viability verdicts are a
  2026-05-16 snapshot; re-run `scripts/phase_a0_diagnostics.py` for a fresh
  read (the trace shows current corpus counts, not recomputed verdicts).
