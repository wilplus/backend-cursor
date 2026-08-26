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

Top to bottom: **Pipelines** (the stage-flows; orange badges mark decision
points), then one card per lane with its live numbers, then **Known gaps**. A
yellow banner at the top lists any sections that failed to load — the rest of
the page still renders.

## The two lanes

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

#### The peer-review side lane (2026-08-03)

`peer flags a prediction → snippet_confidence_reviews → counted, not trained on`

Not a third lane — a **provenance bucket** hanging off Lane 1.
`POST /v2/user/snippets/<id>/confidence-review` (`@require_auth`) captures one
boolean: did the AI get this snippet's confidence call right?

- **Strict boolean.** `"true"` the string is a **400, not a coercion**. This
  is training data; a coerced value is a fabricated label and afterwards it is
  indistinguishable from a real one.
- **Replace-on-reflag.** Unique on `(snippet_id, reviewer_user_id)` — a
  reviewer who changes their mind updates their row. Duplicate rows from one
  rater are junk labels (N3, same rule as the voice game). Different reviewers
  keep their own rows, so peer agreement stays computable.
- **`model_version`** records WHICH prediction was validated; omitted → the
  currently-shadowed version is stamped server-side
  (`learning_serve.current_shadow_version`). "The AI got this right" is
  meaningless without knowing which AI.
- **NOT owner-scoped**, deliberately — this is *peer* review, so the reviewer
  is frequently not the speaker.

**Provenance is the whole game.** These flags are **NON-BLIND** (the reviewer
saw the AI's choice before answering); the coach labels are **BLIND** and stay
that way. Blended indistinguishably, the model would grade its own homework:
validation of a prediction correlates with the prediction, so an unlabelled
mix invites a confirmation feedback loop. Hence the separate table, the
separate `selection_source` (`peer_review`), and the fact that the page counts
the bucket in `by_selection_source` — the **mix** is the thing worth watching.
`training_labels.total` still means blind coach truth only.

**Decision (BE 2026-08-03): `peer_review` rows do NOT count toward the ≥50
total / ≥25-new auto-retrain trigger.** That trigger governs the blind
coach-truth corpus, and letting non-blind validations of the model's own
predictions set its retrain schedule is exactly the loop the split exists to
prevent. Reversible on purpose — flipping it on is one constant
(`services/confidence_reviews.py:COUNTS_TOWARD_RETRAIN_TRIGGER`), whereas a
model already retrained on a bad blend cannot be un-trained. **How to WEIGHT
peer vs. blind coach labels is still a founder call; nothing trains on this
corpus yet** (surfaced as `known_gaps["peer_review_weighting_undecided"]`).

The screen that shows the AI's choice and asks "did it get this right?" is
**not shipped** — it needs founder-signed copy (LIVE LOOP) and must stay off
the blind game rounds, or the AI's read leaks into the blind peer-guess lane
and poisons those labels. This is the capture path only.

Migration to run: `migrations/add_snippet_confidence_reviews.sql`.

### Lane 2 — annotations → surface-specific writer models (SFT/DPO)

`publish/keep/verify capture → one-surface immutable release → candidate fine-tune → production-adapter golden eval → explicit promotion → same surface only`

- Corpus: `admin_annotation_events` (AI draft vs coach final text pairs;
  schema in `migrations/add_admin_copilot_foundation.sql:104`).
  Approve-vs-override on the page is derived from the value hashes
  (equal ⇒ approved verbatim); rows without hashes are "undetermined".
- Export ledger: `admin_annotation_export_runs`
  (`services/annotation_export.py`), fed by cron/webhook
  `routes/internal_webhooks.py` `/v2/internal/annotation-export`.
- Canonical trainable surfaces and their annotation fields live in
  `services/ml_surface_contracts.py`. Mixed-task exports are rejected.
  Contextual `coach_note` corrections belong to `coach_comment_draft`;
  the older one-sentence `admin_comment`/`snippet_drafts` task is a distinct
  prompt and is intentionally excluded until it has its own golden adapter.
- `scripts/export_openai_preference_jsonl.py` requires `--surface` and emits
  write-once train/validation JSONL plus a hash-bound release manifest. The
  split groups by owner, so a user and every project they own stay wholly in
  one partition; owner ids never enter the OpenAI files.
- `scripts/run_openai_preference_finetune.py` accepts only files matching that
  manifest. A successful job is a **candidate**, never a deployment.
- `scripts/evaluate_dpo_candidate.py` injects the candidate in-process and
  runs the real production adapter against that surface's golden dataset. It
  writes a hash-bound pass/fail report and never touches runtime config.
- **Decision point (human promote):** `scripts/promote_openai_model.py`
  requires a fresh, passing report for the same model, release and surface.
  It writes only `runtime_config.openai_surface_model_<surface>`.
- `services/llm.py` resolves those slots only for the registered surface and
  falls back to the pinned base spec otherwise. A Say It Stronger model can
  therefore never become the Moment Suggestion or Ideal Text model.

There is deliberately no auto-promotion flag and no generic copilot promotion
key in this lane.

### ~~Lane 3 — acoustic stress baseline~~ — DELETED 2026-08-03

**Founder decision: stress recognition is dead.** The lane is not paused or
flagged, it is removed, and there is **no replacement trainer**. What it was
pivoted into is the peer-review side lane documented under Lane 1 above.

Deleted (all of it, not just the call sites):

| What | Where it was | Why it had to go |
|---|---|---|
| `POST /v2/internal/stress-model/train` | `routes/internal_webhooks.py` | Ran a `subprocess.run` train pipeline **inside a web request handler**, with a 30-minute timeout |
| `auto_promote` defaulting to **true** | same route | No surviving code path may promote a model artifact without the quality gate **and** a human decision |
| the local-file-path model ref | `config.STRESS_BASELINE_MODEL_PATH`, `_load_baseline_model`'s non-`storage://` branch | A path on Railway's ephemeral filesystem dies at the next deploy. Deleted the mechanism, not just its caller |
| the trainer + dataset export | `scripts/train_stress_classifier_baseline.py`, `scripts/export_stress_snippets_dataset.py` | The whole second-lane trainer goes |
| `runtime_config.stress_baseline_model_path` + its promote writer | `internal_stress_model_train` | The only key the lane promoted |
| the model loader / predictor | `services/stress_snippet_service.py` (`_load_baseline_model`, `_predict_with_baseline_model`, `_feature_vector_for_model`) and its import in `charisma_snippet_service` | Nothing left to load |
| `/admin/snippet-labels/*` | `routes/snippet_labels_routes.py` + `services/snippet_labels.py` | The lane's admin corpus writer (labels on `stress_snippets`), feeding a trainer that no longer exists |
| `POST /v2/user/snippets/<id>/label` | `routes/v2_routes.py` + `db.set_user_snippet_charisma_label` | The legacy user label route; the peer-review capture replaces it |
| `lane_acoustic` | `services/learning_trace.py` | The FE renders two lanes; a trace still serving a third keeps it alive |

**Behavior change — checked before deleting, and it is nil.** The promoted
stress model fed **clip selection only** (the uncertainty term that decides
which clips get offered for labeling); the no-model state already ran
heuristic suspicion scoring. Deleting the model makes that heuristic the
permanent selector — the state the system was already in whenever no model was
promoted, not a new one. The classifier never touched anything surfaced
(AC-9 / CONSTRUCT), so nothing user-facing moved. This closes the old
`charisma_uses_stress_model` known gap **by deletion**: charisma clips were
ranked by the stress classifier, and now nothing ranks them but the heuristic.

**Tables are NOT dropped.** `stress_snippets`, `snippet_labels`, and
`charisma_snippets.user_charisma_label` are all left in place — no table or
column is ever auto-dropped. Nothing reads `snippet_labels` any more.

Regression gate: `test_learning_trace.py::StressLaneIsGoneTests` asserts each
row of that table, so "someone quietly brings the second lane back" fails CI.

The two 2026-07-30 fixes this page shipped with (the 16-vs-17 feature-vector
training/serving skew, and the quality gate not being enforced on
auto-promote) are moot: both lived in code that no longer exists.

## Known gaps (surfaced in the payload's `known_gaps`)

- **`peer_review_weighting_undecided`** — peer flags are captured with their
  own provenance but nothing trains on them: whether and how heavily a
  NON-BLIND peer validation should weigh against a BLIND coach label is a
  founder call. Decide it before any trainer reads that corpus.
- **`dpo_sft_exports_cli_only`** — writer-model exports and copilot
  promotion are CLI scripts only.
- **`no_annotation_model_lineage`** — nothing links annotation
  events/exports to the model trained from them.
- **`phase_a0_corpus_verdicts`** — the PHASE-A0 viability verdicts are a
  2026-05-16 snapshot; re-run `scripts/phase_a0_diagnostics.py` for a fresh
  read (the trace shows current corpus counts, not recomputed verdicts).
