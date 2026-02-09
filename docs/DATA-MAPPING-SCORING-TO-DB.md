# Data mapping: scoring spec → DB columns (locked)

Single source of truth for where each score and metrics breakdown is stored. Aligns CONTRACT-HOMEWORK-FLOW (§2 two metric paths) with existing column names. **Do not rename columns.** Session columns hold scalar rollups; the recording row holds full metrics JSON for recording_2. **`recordings.performance_metrics_v2` is populated only for the recording referenced by `v2_sessions.recording_2_id` (recording_2).** This doc is the bridge between “product terms” and “codebase column names.”

**Related docs:**

| Doc | Purpose |
|-----|---------|
| [CONTRACT-HOMEWORK-FLOW.md](CONTRACT-HOMEWORK-FLOW.md) | Canonical flow, scoring spec (§2 two metric paths), session schema, state machine |
| [SCHEMA-COLUMNS-FOR-MIGRATION-DIFF.md](SCHEMA-COLUMNS-FOR-MIGRATION-DIFF.md) | Exact `v2_sessions` and `recordings` column names for migrations |
| [MIGRATION-PLAN-MINIMAL-DIFF.md](MIGRATION-PLAN-MINIMAL-DIFF.md) | Idempotent SQL to add only missing columns per environment |
| [OPENAPI-V2-STATUS.yaml](OPENAPI-V2-STATUS.yaml) | GET /v2/homework/session/status response schema (session row, no transcripts) |
| [API-GET-STATUS-RESPONSE-SHAPE.md](API-GET-STATUS-RESPONSE-SHAPE.md) | Current GET /status response shape and error codes |

---

## Terminology mapping (product ↔ storage)

| Product term | Meaning | Storage |
|--------------|---------|---------|
| score_1 | warmup_score (3 metrics avg) | `v2_sessions.performance_score_1` |
| score_2 | main_score (5 metrics avg) | `v2_sessions.performance_score_2` + `recordings.performance_metrics_v2` (recording_2 row) |
| final score | average of score_1 and score_2 | `v2_sessions.performance_score_end` |
| score_transcription | task adherence (not in MVP) | none |

---

## Explicit gaps / implications (so nobody is surprised)

1. **You will not be able to show a warmup metric breakdown** (strength/pace/fillers) historically without adding storage later. Today only the scalar `performance_score_1` is stored on the session.
2. The earlier plan “final_score = 0.65 metrics + 0.35 AI” is **not part of this MVP**: there is no place to store task_execution_score, and the end score formula is fixed to `average(score_1, score_2)`.
3. **Re-run on post-answers:** When you re-run scoring after post-answers and update the recording_2 row (`performance_metrics_v2`, `performance_score_v2`), you should also update **`v2_sessions.performance_score_2`** and **`v2_sessions.performance_score_end`** so the session row and recording row stay consistent. (Recommended: yes.)

**Sync invariant (must hold after any re-score operation):**

- `v2_sessions.performance_score_2 == recordings.performance_score_v2` where `recordings.id = v2_sessions.recording_2_id`.
- `v2_sessions.performance_score_end == (performance_score_1 + performance_score_2) / 2` (clamped 0..1).

This prevents drift and makes QA straightforward.

---

## 1. Recording 1 (warm-up) — 3 metrics only

**Computation:** `score_1 = avg(pace, strength, fillers)`. No keywords/emotion (answers come later).  
**Source:** `compute_performance_score_1(wpm, strength_raw, filler_count)` in `services/metrics_v2.py`.

| What | Where | Column / shape |
|------|--------|----------------|
| Scalar score (0–1) | **v2_sessions** | **performance_score_1** (FLOAT) |
| 3-metric breakdown | **Not stored today** | — |
| Recording reference | **v2_sessions** | **recording_1_id** (UUID → recordings.id) |
| On recording row | **recordings** | No `performance_score_v2` or `performance_metrics_v2` written for recording_1 |

**Optional (post-MVP):** To persist the 3-metric breakdown for recording_1, write to the **recording** row (same as recording_2):  
`performance_metrics_v2` = `{ "pace": { raw, normalized, explanation }, "strength": { ... }, "fillers": { ... } }` and optionally `performance_score_v2` = same value as session.performance_score_1. No change to schema; column already exists on recordings.

---

## 2. Recording 2 — 5 metrics (full rubric)

**Computation:** `score_2 = avg(pace, strength, fillers, emotion_achieved, keywords_used)`.  
**Source:** `compute_metrics_v2(...)` in `services/metrics_v2.py`. Emotion/keywords come from post-answers; on first upload we use placeholder (e.g. emotion_achieved=False, keywords=[]); after post-answers we re-run with real answers and overwrite.

| What | Where | Column / shape |
|------|--------|----------------|
| Scalar score (0–1) | **v2_sessions** | **performance_score_2** (FLOAT) |
| 5-metric breakdown | **recordings** (recording_2 row) | **performance_metrics_v2** (JSONB): `{ "pace": { raw, normalized, explanation }, "strength", "fillers", "emotion_achieved", "keywords_used" }` |
| Label snapshot | **recordings** (recording_2 row) | **metric_labels_snapshot_v2** (JSONB): `{ code: { left_label, right_label } }` |
| Same scalar (denormalized) | **recordings** (recording_2 row) | **performance_score_v2** (FLOAT) |
| Recording reference | **v2_sessions** | **recording_2_id** (UUID → recordings.id) |

**Flow:**  
- On POST recording-2: write recording with `performance_score_v2`, `performance_metrics_v2`, `metric_labels_snapshot_v2` (initial run with emotion/keywords placeholder). Update session with `recording_2_id`, `performance_score_2`, status → post_questions.  
- On POST post-answers: re-run `compute_metrics_v2` with real emotion/keywords; `update_recording` with new `performance_metrics_v2` and `performance_score_v2`; then compute `performance_score_end` and report.

---

## 3. Session-level end score

| What | Where | Column / formula |
|------|--------|------------------|
| End score (0–1) | **v2_sessions** | **performance_score_end** (FLOAT) |
| **MVP formula** | — | `(performance_score_1 + performance_score_2) / 2`, clamped 0..1 |
| **Future (optional)** | — | e.g. weighted: `0.65 * performance_score_2 + 0.35 * score_transcription`; then store result in **performance_score_end** or a separate column. |

No separate column named `final_score` in current schema. **performance_score_end** is the single session-level “final” score.

---

## 4. Task execution / score_transcription (optional, not yet implemented)

**Meaning (contract):** Task adherence — did the user address the generated task? Content relevance / instruction following. Separate from delivery metrics (score_2).

| What | Where | Column (reserved) |
|------|--------|--------------------|
| Task adherence score (0–1) or JSON | **v2_sessions** | **score_transcription** (TEXT or FLOAT; add when implementing) |
| Or per-recording | **recordings** | Optional **task_execution_score** (FLOAT) on recording_2 row |

**Decision:** Add **v2_sessions.score_transcription** when product defines the metric (e.g. LLM or rule-based). Use it in report and optionally in a future **performance_score_end** formula. No column exists today; migration when needed.

---

## 5. Summary table (quick reference)

| Metric / score | Session column | Recording column (which row) |
|----------------|----------------|------------------------------|
| score_1 (3 metrics) | **performance_score_1** | — (optional later: performance_metrics_v2 on recording_1) |
| score_2 (5 metrics) | **performance_score_2** | **performance_score_v2** + **performance_metrics_v2** + **metric_labels_snapshot_v2** (recording_2) |
| end score | **performance_score_end** | — |
| task execution / adherence | **score_transcription** (future) | — or task_execution_score on recording_2 (future) |

---

## 6. Naming conventions (no renames)

- **performance_score_1** = warm-up scalar (3 metrics).  
- **performance_score_2** = main rubric scalar (5 metrics).  
- **performance_score_v2** on **recordings** = same numeric value as score_2 for that recording (denormalized).  
- **performance_metrics_v2** on **recordings** = full breakdown (3 keys for recording_1 if we add it, 5 for recording_2).  
- **performance_score_end** = session-level final score; MVP = average of score_1 and score_2.  

No new column names required for MVP; optional additions are **score_transcription** (session) and/or **task_execution_score** (recording) when implemented.

---

## Next decision: Option A vs Option B

- **Option A (recommended for shipping fast):** Keep MVP strictly metrics-only (as above) and ship. Add score_transcription later with new columns + new final score formula when product is ready.
- **Option B:** Add the missing columns now (minimal: `recordings.task_execution_score` + reuse `v2_sessions.performance_score_end` or add `v2_sessions.final_score`) and ship with AI task-adherence scoring included. Requires defining the formula (e.g. 0.65×score_2 + 0.35×task_execution_score) and where it is stored.
