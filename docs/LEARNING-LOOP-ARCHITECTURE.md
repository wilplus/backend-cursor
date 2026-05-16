# Learning-loop architecture — what we need to wire so corrections actually train the system

This is a **requirements doc**, not a how-to. Read this to understand the parts we'd add, what each part feeds, and the order to build them in. Then we go decide what to ship.

Today's state: data is being captured passively. Nothing automatically improves. This doc describes what it takes to close the loops.

---

## 0. The two distinct learning loops

These are not the same problem and need separate plumbing. Conflating them is the first design mistake to avoid.

| Loop | Input signal | Output | Method | Math |
|---|---|---|---|---|
| **L1 — Voice labeling classifier** | Admin label (charisma / stress / neither) + user Yes/No label on snippets | A probability per snippet ("78% charismatic, 22% stress") that drives auto-extraction and auto-label suggestions | Train a small classifier on acoustic features → label | Logistic regression / shallow MLP on hand-crafted features. **No OpenAI involved.** |
| **L2 — LLM tone/quality fine-tune** | Admin text edits (admin_comment, follow_up_question, evaluator_rationale, ...) | A fine-tuned LLM that drafts in the lead coach's voice and asks better next-questions | Submit (prompt, draft, admin's preferred output) pairs as OpenAI SFT / DPO | OpenAI fine-tune API; promote model ID via `runtime_config` |

The user's question was specifically about charisma/stress labeling — that's L1. But the system also needs L2 because user-facing chat tone is dormant. Wire both.

---

## 1. L1 — Voice labeling classifier (charisma + stress)

### 1.1 What "labeling" means here
For every snippet (`charisma_snippets` row) we want to produce a vector:
```
{ charisma_probability: 0..1, stress_probability: 0..1, confidence: 0..1 }
```
This drives:
- **Auto-extraction**: the recording-1 background job already extracts snippets from peaks; the classifier sharpens which peaks are "really charisma" vs "really stress"
- **Auto-label suggestion**: pre-fills `snippet_type` so admin only has to confirm, not classify from scratch
- **Charisma profile** (`services/charisma_profile.py`): per-user aggregate "this user is X% Stressor, Y% Charismatic"

### 1.2 Signals already captured (audit)
- ✅ `charisma_snippets.snippet_type` — admin's label on charisma side ("charisma"|"stress"|"unlabeled")
- ✅ `stress_snippets.coach_label` — admin's label on stress side ("stress"|"no_stress")
- ✅ `charisma_snippets.user_charisma_label` — user's Yes/No from state-machine STEP 2 (added in commit history around `ba3751e` + `cda3c28`)
- ✅ Acoustic features per snippet — wpm, pitch, fillers, dynamic_db, energy, pause_strength, filler_density, plus the snippet boundaries

### 1.3 Signals we need to add
- 🔴 **Acoustic feature snapshot at LABEL time, not snippet-extraction time** — features can drift if the audio is reprocessed. Pin the feature vector that the admin saw when they labelled, so training data stays stable.
- 🔴 **Inter-rater agreement signal** — when admin label disagrees with user label (the AI says charismatic, admin agrees, user says no), that's high-signal training data. Right now we capture both labels but don't surface the disagreement. Add a `label_agreement` field computed at write time.
- 🟡 **Label confidence** — admin chose "charisma" but was hesitant? A 1-3 star confidence dropdown in the admin labeling UI would weight the training example. Optional but improves data quality.
- 🟡 **Negative examples** — snippets the admin explicitly labels as "neither charisma nor stress / just neutral speech". Today the schema only supports positive labels; "unlabeled" conflates "haven't reviewed yet" with "reviewed and rejected". Add `snippet_type='neutral'` or a separate `is_neutral` flag.

### 1.4 Storage layer additions
- 🔴 **New table `voice_label_training_examples`** — denormalised, training-ready rows:
  ```sql
  ( id uuid pk,
    snippet_id uuid fk,
    user_id uuid,
    features jsonb,            -- snapshot at label time
    coach_label text,          -- "charisma"|"stress"|"neutral"|"reject"
    user_label text,           -- "yes"|"no"|null
    label_agreement text,      -- "both_agree"|"admin_only"|"user_only"|"disagree"
    label_confidence smallint, -- 1-3
    captured_at timestamptz,
    excluded_from_training bool default false,   -- governance kill-switch
    excluded_reason text )
  ```
  Why a dedicated table: keeps training data immutable even if the underlying `charisma_snippets` row is edited / re-extracted / deleted (right-to-be-forgotten). The export job reads from here, not from the live snippet table.
- 🟡 **Trigger / background worker** that writes a row into `voice_label_training_examples` every time an admin or user labels a snippet. Idempotent (one row per snippet+labeler pair).

### 1.5 Training pipeline
- 🔴 **New script `scripts/train_voice_label_classifier.py`**:
  - Reads N most recent rows from `voice_label_training_examples` where `excluded_from_training=false`
  - Splits 80/20 train/val
  - Trains a logistic regression (or shallow MLP) on the feature vector → multi-class label
  - Outputs `weights.json` matching the existing `stress_snippet_service._load_baseline_model()` shape (so the runtime resolver works unchanged):
    ```json
    { "weights": {...}, "norm_mean": [...], "norm_std": [...], "feature_order": [...] }
    ```
  - Reports train/val accuracy + per-class F1
  - Uploads the JSON to R2/Supabase Storage
  - Calls `db.upsert_runtime_config("charisma_baseline_model_path", "<bucket>/<key>")` IFF val accuracy ≥ N% over the currently-deployed model
  - On regression: don't promote, log to Sentry
- 🟡 **Mirror script for stress** — `train_stress_classifier.py` does the same for the existing stress channel
- 🟡 **Unified script** (preferred) — one binary, `--channel charisma|stress`

### 1.6 Runtime layer additions
- ✅ `runtime_config.stress_baseline_model_path` — already exists, already wired into `stress_snippet_service._load_baseline_model`
- 🔴 `runtime_config.charisma_baseline_model_path` — new key. Mirror the existing pattern in a new helper inside `charisma_snippet_service.py`:
  ```python
  def _load_charisma_baseline_model() -> Optional[dict]: ...
  ```
- 🔴 Wire the charisma classifier into `generate_charisma_snippets_for_recording` so each extracted snippet gets a `classifier_charisma_probability` written alongside `classifier_stress_probability`
- 🟡 Cold-start fallback: when the classifier isn't loaded (path empty), don't crash — just skip the probability fields. UI shows "—" instead of a number.

### 1.7 Scheduling
- 🔴 **New Railway cron service** (mirror `Dockerfile.annotation-cron`):
  - `Dockerfile.classifier-retrain-cron`
  - Schedule: weekly (Sundays 04:00 UTC) — slow enough to accumulate enough new labels, fast enough that the model stays fresh
  - Runs `scripts/train_voice_label_classifier.py --channel charisma --channel stress`
- 🟡 **On-demand retrain endpoint** — `POST /v2/admin/internal/retrain-voice-classifier` (admin-only) so a coach can trigger after a big labeling session without waiting for the cron

### 1.8 Admin observability (the page that doesn't exist yet)
- 🔴 **Admin → Voice Labeling → Model Status** page showing:
  - Currently deployed model path + uploaded_at + val accuracy
  - Label counts in `voice_label_training_examples` since last retrain
  - Last 5 retrain runs (timestamp, count, val accuracy, promoted/skipped)
  - One-click "retrain now" button (calls the on-demand endpoint above)
  - Confusion matrix of the current model on the latest val set
- 🟡 **Per-snippet "why this label" overlay** — when admin opens a snippet, show `classifier_charisma_probability` and the top 3 contributing features. Helps admins understand if they should trust the suggestion.

---

## 2. L2 — LLM fine-tune (admin's text edits → better drafts and chat tone)

### 2.1 What "learning" means here
The admin reviews drafts and either approves or edits. We want the LLM to drift toward the lead coach's voice over time. Currently the `_chat_model("copilot")` path supports this via OpenAI fine-tune + auto-promote. We need to:
- Extend the same pattern to other call sites that are still hardcoded `gpt-4o-mini`
- Wire automation (today fine-tune submission is manual CLI)

### 2.2 Channels to add
| Channel key (proposed) | Used by | Currently hardcoded at |
|---|---|---|
| `openai_copilot_model` ✅ existing | Admin draft generators (email, task, script, report_comment) | already on the resolver |
| `openai_interview_model` 🔴 new | `_generate_llm_question` for `/v2/public/interview/next-question` and `/v2/user/chat/first-question` | [routes/v2_routes.py:8008](routes/v2_routes.py:8008) hardcodes `gpt-4o-mini` inside |
| `openai_awareness_model` 🔴 new | `/v2/coaching/turn` (awareness skill flow) | [routes/v2_routes.py:9322](routes/v2_routes.py:9322) |
| `openai_state_machine_model` 🔴 new | `/v2/coaching/state-machine/turn` | [routes/v2_routes.py:9566](routes/v2_routes.py:9566) |
| `openai_snippet_drafts_model` 🔴 new | `services/snippet_drafts.py` — generates ai_draft_admin_comment + ai_draft_follow_up_question | [services/snippet_drafts.py:46](services/snippet_drafts.py:46) `_MODEL = "gpt-4o-mini"` |
| `openai_coach_label_notes_model` 🔴 new | Stress-snippet coach_label_notes AI prefill | scattered, find via `ai_draft_coach_notes` writers |

Why separate channels: each call site has a different output contract (interview returns plain text with `|||`, awareness returns `<anchor> ||| <scenario> [ADVANCE]`, state-machine returns strict JSON, snippet drafts return short prose). A single fine-tuned model trying to span all of them will sometimes emit the wrong shape for the wrong call site. **One model per output contract** is the safe default.

### 2.3 Per-channel JSONL exports
Each channel needs an export script that reads `admin_annotation_events` filtered to that channel's field_names and emits OpenAI SFT-format JSONL `{"messages": [system, user, assistant]}`:

- `export_copilot_jsonl.py` ✅ exists as `export_openai_finetuning_jsonl.py` (read both)
- 🔴 `export_interview_jsonl.py` — **NEEDS A NEW SIGNAL**: admins don't currently edit the bot's next question after it's been asked. To train this channel we need to capture admin's preferred question alongside the AI's chosen one. Three options:
  - A. Admin reviews the question pre-send in a queue (high friction)
  - B. Admin retroactively flags bad questions with a "regenerate" or "edit" action on the per-session timeline (medium friction)
  - C. Use the existing `queued_override_question` admin action as the preferred-output signal — if admin queued a specific question, that IS the lead coach's preferred wording for that context (low friction, already wired)
  - **Recommended: C first, then add B as a follow-up if data volume is too low.**
- 🔴 `export_awareness_jsonl.py` — pulls (prompt, AI bubbles, admin's edited bubbles). Today the awareness flow doesn't expose admin editing of the bubble text. Add an admin "edit this bubble" UI in the coaching session timeline, store the edit, capture as `field_name='awareness_bubble'` annotation event.
- 🔴 `export_state_machine_jsonl.py` — same pattern: admin reviews state-machine narration in coaching transcripts, edits if wrong, stored as `field_name='state_machine_narration_step_N'`. The schema gives us per-step granularity for free.
- 🔴 `export_snippet_drafts_jsonl.py` — easy, the data already exists: `(ai_draft_admin_comment, admin_comment)` and `(ai_draft_follow_up_question, follow_up_question)`. Just filter the existing `admin_annotation_events` rows for the two `field_name`s and emit JSONL.

### 2.4 Fine-tune orchestrator
- ✅ `scripts/run_openai_preference_finetune.py` exists, works for one JSONL+channel combo
- 🔴 **New orchestrator script `scripts/run_all_channels_finetune.py`** that:
  1. For each channel: run its export script → JSONL
  2. Validate JSONL min row count (skip channels under threshold, e.g. 50 examples)
  3. Split into train/eval (90/10)
  4. Submit fine-tune job to OpenAI with base model `gpt-4.1-mini-2025-04-14` or `gpt-4o-mini-2024-07-18` (configurable per channel)
  5. Poll until complete
  6. **Run a held-out eval**: for each eval example, get the new model's output, compare to admin's preferred output via a separate scoring model (gpt-4o judge) → produces a per-channel quality delta
  7. Auto-promote IFF eval improves over the currently-deployed model (`runtime_config.<channel_key>`)
  8. Log everything to a new `model_training_runs` table (job id, base model, train count, eval delta, promoted, started_at, completed_at)

### 2.5 Scheduling
- 🔴 Second Railway cron service (mirror `Dockerfile.annotation-cron`):
  - `Dockerfile.finetune-orchestrator-cron`
  - Schedule: monthly (1st of month, 02:00 UTC) — OpenAI fine-tune cost is non-trivial; monthly is the safe default
  - Runs `scripts/run_all_channels_finetune.py`
- 🟡 On-demand: `POST /v2/admin/internal/retrain-channel` body `{channel: str}` (admin-only) so the lead coach can trigger after a high-edit week.

### 2.6 Migrate call sites
- 🔴 Replace `model="gpt-4o-mini"` with `model=service._chat_model("interview")` in `routes/v2_routes.py` at the three line numbers above + the awareness path
- 🔴 Replace `model=_MODEL` with `model=service._chat_model("snippet_drafts")` in `services/snippet_drafts.py`
- 🔴 Same for the coach_label_notes draft generator
- Each call site keeps backward compat — if no runtime_config row exists yet, resolver falls through to the hardcoded `gpt-4o-mini` default. **Zero-impact change** until the first fine-tune lands.

### 2.7 Admin observability
- 🔴 **Admin → AI Models** page showing:
  - One row per channel: current model ID, base model, promoted_at, last training run summary (count, eval delta), train data count since last promotion
  - "Retrain now" button per channel
  - "Rollback to previous" button per channel (looks up the previous `runtime_config` value via the new `model_training_runs` history table)
  - "View training data" link — opens a sample of recent (prompt, AI draft, admin final) tuples so the coach can verify the data looks right

### 2.8 Eval / safety
- 🔴 **Held-out eval set** — for each channel, reserve the 10% most recent examples and never train on them. Used as the auto-promote gate.
- 🟡 **Canary deployment** — route 10% of traffic to the new model for 24h before full promote. Compare downstream metrics (user engagement, score deltas, admin edit rates). Auto-rollback on regression. **Significant engineering — defer to phase 2.**
- 🔴 **Cost cap** — `MAX_MONTHLY_FINETUNE_USD` env var. Orchestrator hard-stops if cumulative job cost in the calendar month exceeds the cap.
- 🟡 **PII scrubbing** — before any text leaves the DB into a JSONL file, run it through a redactor (regex for emails, phone numbers, names where possible). Required if you're shipping training data to OpenAI under a privacy-sensitive policy.

---

## 3. Cross-cutting: governance

### 3.1 Data ownership / right-to-be-forgotten
- 🔴 When a user is deleted, also delete all rows in `voice_label_training_examples` and `admin_annotation_events` keyed to that user. Add a `purge_user_training_data(user_id)` db method called from the existing user-deletion path.
- 🔴 OpenAI fine-tune snapshots are immutable on their side. If a user requests deletion and they're in a deployed fine-tune, the only remedy is to retrain WITHOUT that user's data and re-promote. Document this in the privacy policy.

### 3.2 Disagreement handling
- 🔴 When admin label disagrees with user label, the row STILL goes into training but with `label_agreement='disagree'`. The training script can weight these (count them as 0.5 instead of 1.0) or hold them out entirely depending on the experiment. Make this a CLI flag.

### 3.3 Audit log
- 🔴 Every model promotion writes a `model_training_runs` row. Never silent-update `runtime_config` without a corresponding history entry. Lets you answer "why did the coach insight tone change last Tuesday?".

### 3.4 Kill switches
- 🔴 `runtime_config.classifier_inference_enabled` (bool, default true) — flip to false to disable the classifier entirely (e.g. it's producing garbage)
- 🔴 `runtime_config.openai_finetune_enabled` (bool, default true) — flip to false to halt all fine-tune cron jobs
- 🟡 Per-channel kill switches if you want finer control: `openai_<channel>_finetune_enabled`

---

## 4. Data flow diagram (prose)

**L1 — classifier loop**:
```
admin labels snippet → snippet_type / coach_label column write
user clicks Yes/No in state-machine STEP 2 → user_charisma_label column write
                       ↓ both trigger background worker
voice_label_training_examples row append (features snapshot + labels + agreement)
                       ↓ weekly cron
train_voice_label_classifier.py:
  read N rows → train logistic → eval on held-out → if improves, upload JSON to storage,
  upsert runtime_config.{charisma|stress}_baseline_model_path → record run in model_training_runs
                       ↓ next snippet extraction
recording_1_job runs → charisma_snippet_service.generate_charisma_snippets_for_recording loads
the new model (via runtime_config) → writes classifier_charisma_probability per snippet
                       ↓
admin UI shows AI-suggested label, admin confirms or overrides → back to top
```

**L2 — LLM fine-tune loop**:
```
admin reviews AI-drafted text (admin_comment, follow_up_question, evaluator_rationale,
  next question via queued_override_question, awareness bubble, state-machine narration)
admin saves verbatim or edited
                       ↓ at publish time
record_snippet_publish_annotations writes one admin_annotation_events row per field
                       ↓ daily annotation export cron (already exists)
admin_annotation_events shipped to wherever
                       ↓ monthly orchestrator cron
run_all_channels_finetune.py:
  per channel:
    export JSONL → validate min count → 90/10 split → OpenAI fine-tune job submit → poll →
    held-out eval via judge model → compare to currently-deployed model → if delta > threshold,
    auto-promote (upsert runtime_config.openai_<channel>_model) → record run in model_training_runs
                       ↓ next inference call
service._chat_model("<channel>") resolves the new fine-tuned model → response sounds more like
  the lead coach → admin reviews next draft → back to top
```

---

## 5. Sequencing — what to build first

A pragmatic order. Each phase ships independently and provides value.

### Phase A — make L1 functional (charisma classifier, 1-2 weeks)
1. New table `voice_label_training_examples` + trigger/worker that populates it from existing label writes
2. `train_voice_label_classifier.py --channel charisma` writing to `runtime_config.charisma_baseline_model_path`
3. `_load_charisma_baseline_model` helper in `charisma_snippet_service.py`, wire into `generate_charisma_snippets_for_recording`
4. Weekly cron service (mirror annotation-export pattern)
5. Admin observability page (just current model status — no fancy charts yet)

**Outcome**: every new snippet ships with `classifier_charisma_probability`. The classifier improves weekly. Admin gets pre-filled label suggestions.

### Phase B — extend L1 to stress + add user-label signal (1 week)
6. Same script wired for `--channel stress`
7. Include `user_charisma_label` in the training-example writer
8. `label_agreement` computation
9. Backfill `voice_label_training_examples` from historical labels (one-off script)

**Outcome**: stress classifier also auto-retrains. User Yes/No labels become first-class training signal. Disagreements become weighted training data.

### Phase C — migrate L2 call sites onto runtime_config (3-5 days)
10. Add new channel keys (`interview`, `awareness`, `state_machine`, `snippet_drafts`, `coach_label_notes`)
11. Replace hardcoded `gpt-4o-mini` with `service._chat_model("<channel>")` at each call site
12. Verify: no `runtime_config` row = resolver falls through to default. No behavior change in prod.

**Outcome**: zero-impact deploy. Foundation ready for fine-tunes.

### Phase D — wire L2 automation (1-2 weeks)
13. Per-channel export scripts (snippet_drafts first — easiest, data exists)
14. `run_all_channels_finetune.py` orchestrator with eval gate
15. `model_training_runs` table + history endpoint
16. Monthly cron service
17. Admin → AI Models observability page

**Outcome**: snippet draft model auto-trains monthly from admin edits.

### Phase E — capture missing L2 signals (ongoing)
18. Admin UI: "edit this bubble" on awareness coaching transcripts
19. Admin UI: "edit this narration step" on state-machine transcripts
20. Frontend wiring for the queued_override_question → annotation event when admin uses it
21. Re-run Phase D for the new channels as data accumulates

**Outcome**: every LLM channel learns from corrections.

---

## 6. What I'd push back on / open questions

These are the design decisions that aren't obvious. Worth answering before building:

1. **One classifier or two?** Charisma and stress could be a single multi-class model (charisma | stress | neither) or two binary classifiers (charisma vs not, stress vs not). Two binary is more flexible (a snippet can be both somewhat charismatic AND somewhat stressed), single multi-class is simpler. **My default: two binary**, but worth deciding before building Phase A.

2. **Trust admin labels equally?** Or weight by admin tenure / inter-rater agreement? **My default: trust equally for v1**, add weighting in Phase E if data shows lead coach disagreeing with junior coaches.

3. **Train on user labels at all, or just use them as eval?** User labels are noisier than admin labels but vastly more numerous. **My default: train on both with disagreement-down-weighting**, hold out a sample as eval.

4. **Per-tenant fine-tunes or one shared model?** If you sell to multiple companies, each may want their own coach voice. OpenAI supports per-org fine-tunes but cost scales linearly. **My default: shared until 3+ paying tenants ask for their own**, then split.

5. **What's the eval judge model?** If you use `gpt-4o` to grade `gpt-4o-mini-ft`, the judge is more powerful than the candidate — fair. If you use the same family, it can introduce bias. **My default: `gpt-4o` as judge** since cost is bounded (10% eval set).

6. **Awareness flow `[ADVANCE]` token in training data?** Including it in JSONL means the fine-tuned model learns to emit it correctly. Excluding it means the model might forget. **My default: include**, validate that generated outputs still pass the parser.

7. **State-machine JSON schema in training data?** OpenAI fine-tune supports structured outputs. The training data should include the schema constraint so the fine-tuned model knows to obey it. Requires testing.

---

## 7. File / line map of what would change

| Touch | What | Why |
|---|---|---|
| 🔴 NEW `migrations/add_voice_label_training_examples.sql` | Table + indexes | L1 storage layer |
| 🔴 NEW `migrations/add_model_training_runs.sql` | Audit table | Both loops |
| 🔴 NEW `services/voice_label_training.py` | Write-on-label worker, idempotent upsert | L1 capture |
| 🔴 NEW `scripts/train_voice_label_classifier.py` | Read training data → train → eval → promote | L1 training |
| 🔴 NEW `bin/railway-classifier-retrain-cron.sh` + `Dockerfile.classifier-retrain-cron` | Weekly cron | L1 scheduling |
| 🔴 EDIT `services/charisma_snippet_service.py` | Add `_load_charisma_baseline_model`, wire into snippet generation | L1 inference |
| 🔴 NEW per-channel export scripts under `scripts/` | Pull annotation_events → JSONL per channel | L2 data |
| 🔴 NEW `scripts/run_all_channels_finetune.py` | Orchestrator with eval gate | L2 training |
| 🔴 NEW `bin/railway-finetune-orchestrator-cron.sh` + `Dockerfile.finetune-orchestrator-cron` | Monthly cron | L2 scheduling |
| 🔴 EDIT `routes/v2_routes.py` ~5 call sites | Replace `gpt-4o-mini` literal with `_chat_model("<channel>")` | L2 inference |
| 🔴 EDIT `services/snippet_drafts.py` | Same | L2 inference |
| 🔴 NEW admin BFF + page `frontend-admin-panel/.../models` | Model status + retrain buttons | L1+L2 observability |
| 🔴 NEW `routes/v2_routes.py` endpoints: GET model status, POST retrain channel | Power the admin page | L1+L2 |

---

## 8. What this does NOT replace

- The few-shot retrieval pool (Phase 1) — still useful and complementary. Fine-tuning bakes the average tone; few-shot adapts per-call to the specific user's history.
- The user-profile / baseline summary / Master Score augmentations in interview prompts — those are runtime in-context steering, orthogonal to weight updates.
- The hardcoded skill prompts (`charisma.py`, `stress.py` _AWARENESS_PROMPT) — those define the contract / persona. Fine-tuning teaches the model to fulfil the contract more on-voice. Don't remove the prompts; the model still reads them.
- The signal-processing acoustic features pipeline. Fine-tuning the LLM doesn't change the wpm / pitch / dynamic_db numbers — those are deterministic.

---

## 9. Estimated effort (rough)

| Phase | Eng days | Risk |
|---|---|---|
| A (charisma classifier wired + retraining) | 5-8 | Low — pattern exists for stress |
| B (stress + user labels + agreement) | 3-5 | Low |
| C (call site migration, no behavior change) | 2-3 | Very low — backward-compatible |
| D (fine-tune orchestrator + monthly cron + snippet drafts channel) | 8-12 | Medium — eval design needs care |
| E (capture missing signals via new admin UI affordances) | 5-10 per channel | Medium — coordination with frontend |

Total to get from "data collecting" to "all channels self-improving monthly": **~25-40 eng days** spread over 2-3 months realistic calendar time given everything else in flight.

---

## 10. Decision checkpoint

Before any of this gets built, agree on:
- [ ] Two binary classifiers or one multi-class? (Q1 in §6)
- [ ] Train on user labels or eval-only? (Q3)
- [ ] Per-tenant or shared LLM fine-tunes? (Q4)
- [ ] Which channels are highest priority? (default order is snippet_drafts → interview → awareness → state_machine → coach_label_notes based on data volume + impact)
- [ ] Cost cap for fine-tuning per month? (recommend $50-200 to start)
- [ ] Acceptable eval-delta threshold for auto-promote? (recommend +5% accuracy or +0.1 judge score)
- [ ] Who is the lead coach whose voice we're targeting? (matters for judging "on-tone" vs "off-tone" in eval)

Once those are answered, Phase A is mechanical.
