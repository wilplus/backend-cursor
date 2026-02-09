# Homework flow: gap answers + open decisions

This doc answers what **is already defined in code**, what is **frontend-only**, and what **you must decide** (product/backend). References the 12 gap groups from the review.

**Canonical decisions are now in:** **`CONTRACT-HOMEWORK-FLOW.md`** (session schema, scoring, focus “no eligible” → easiest, context_1/2, score_transcription vs score_2, score_end, report schema, admin policy, state machine, QC). Use that as the single source of truth.

---

## 1) Entity & ID model

### Answered from code

- **Session container exists.** `v2_sessions` is the attempt/session: it ties together `user_id`, `status`, `recording_1_id`, `recording_2_id`, `context_short`, `performance_score_1` / `performance_score_2` / `performance_score_end`, `selected_task_id` (focus task), `metric_answers`, `report_id`, `context_long_entries`, `post_question_ids`. One row = one run. Partial completion is supported by `status`.
- **Warmup_task vs focus_task vs “task” (AI):**
  - **Warmup_task** = row in `v2_warm_up_tasks` (per student) or pool `v2_warm_up_task_pool`. Has `text`, `max_performance_score`. **Not** stored on session by ID in current schema (we only store which warm-up was *shown* implicitly via selection at start; we could add `warm_up_task_id` to session if you want reproducibility).
  - **Focus_task** (in homework flow) = row in **`v2_tasks`** (`title`, `prompt_text`, `min_task_score`). Session stores `selected_task_id` → FK to `v2_tasks`. So the *chosen* focus task is bound to the session.
  - **Generated “task”** = output of `generate_final_task(...)`. **Not** stored in DB as a separate entity; only returned to client. So “task” here = the 2-sentence instruction string. If you want reproducibility, we’d need to store it (e.g. `session.final_task_text` or in report).
- **Versioning / admin edits:** **Not implemented.** There are no `metric_version_id`, `rubric_version_id`, or immutable task versions. If admin edits a task or metric definition, past sessions keep their stored scores and stored `selected_task_id`; they are **not** re-scored. So effectively **scores are frozen** per session; no “version” is stored.

### You decide

- **Gap:** Canonical schema for “Session/Attempt” + optional **version IDs** for warmup/focus tasks, metrics, questions, prompts.
- **Questions for you:**
  1. Do you want **reproducibility** so old reports stay valid after admin edits? If yes, we need either (a) immutable versions (e.g. copy-on-write when admin edits) or (b) store snapshot IDs/version IDs on the session (e.g. `metric_snapshot_id`, `focus_task_snapshot_id`).
  2. Do you want `warm_up_task_id` (and optionally pool id) stored on `v2_sessions` so “which warm-up was used” is explicit for history/audit?

---

## 2) Warmup scoring / metric definition

### Answered from code

- **Metric output shape:** All metrics are **normalized to 0–1** in `services/metrics_v2.py`. Each returns a float in [0, 1]. Stored on recording as `performance_metrics_v2` (per-metric `raw`, `normalized`, `explanation`).
- **score_1 aggregation:** **Unweighted average** of 3 metrics: `(pace_n + strength_n + fillers_n) / 3.0`. No weights; no minimum rule. Clamped to [0, 1].
- **score_2 aggregation:** Unweighted average of **5** metrics: pace, strength, fillers, emotion_achieved, keywords_used. Same 0–1 scale.
- **Normalization:** Done inside each metric (smoothstep, target bands). Pace: 120–160 WPM = 1.0; strength: heuristic around -25 dB; fillers: ≤3 = 1.0, then decay.
- **Failure modes:** **Partially defined in code.** If `strength_raw` is None, strength gets 0.5. If transcript is empty, WPM can be 0 (pace then 0.5). There is **no** explicit “transcription failed” or “audio too short” gate; flow continues. No explicit fallback for “metrics cannot be computed” (we’d need to add a fallback score or block progression).

### You decide

- **Gap:** Formal scoring spec: per-metric scale (already 0–1), **weights** (currently none), aggregation (currently average), **fallbacks** when transcript missing / too short / language mismatch.
- **Questions for you:**
  1. Do you want **weights** for score_1 or score_2 (e.g. fillers 0.4, pace 0.3, strength 0.3)?
  2. When transcription fails or audio is too short: **block** progression (require re-record) or **fallback** to a default score (e.g. 0.5) and continue?
  3. Should we **store per-metric evidence/explanations** on the session for the report? We already store them on the recording in `performance_metrics_v2`; we could copy a subset to session for the coach report.

---

## 3) Focus_task selection

### Answered from code

- **Eligibility:** Focus task (from `v2_tasks`) is eligible if `min_task_score <= performance_score_1`. So “score_1 = 0.5” → tasks with `min_task_score` 0, 0.1, …, 0.5.
- **No match:** If **no** task matches, `select_focus_task_for_performance_score_1` returns **None**. Caller does not currently handle None explicitly (we’d need to return a clear error or fallback task).
- **Tie-breaking:** If **many** match: **random.shuffle(matching); return matching[0]** (random, not LRU or curriculum).
- **focus_task “score” meaning:** In `v2_tasks` the field is **min_task_score** = “minimum warmup score required to be shown this task” (threshold). So it’s “required level” / “difficulty threshold.”
- **Metric_questions influencing focus:** **Not used.** Focus is chosen only from `performance_score_1` and `assigned_next_task_ids`. Metric answers are collected *after* focus is chosen and used only for **task generation**, not for focus selection.

### You decide

- **Gap:** Deterministic (or documented) selection + “no match” behavior + optional use of metric_questions for personalization.
- **Questions for you:**
  1. When **no** focus_task has `min_task_score <= score_1`, what should happen? (e.g. return **easiest** task, return **nearest** above score_1, or **block** with “no task available”?)
  2. When many qualify, keep **random**, or switch to **rotation / LRU / curriculum order**?
  3. Should **metric_questions** (or user goals) influence focus_task choice in a future version? (Currently no.)

---

## 4) Transcription / context

### Answered from code

- **What is stored:** Recording has **transcription_text** (raw transcript from OpenAI). No separate “cleaned” transcript, no diarization, no timestamps in DB. **context_1** = **context_short** = AI **summary** of recording_1 transcript (`generate_context_short`), stored on **session**. **context_2** is **not** a separate field; only recording_2’s **transcription_text** exists (no second summary).
- **Privacy / retention:** Not enforced in code (no retention policy or consent flag in schema). **You** decide policy and whether to add fields (e.g. `transcript_retention_until`, `consent_for_storage`).
- **Language:** No detection or per-language rubric in code. Single pipeline.

### You decide

- **Gap:** Transcript schema (raw vs cleaned, retention), and whether **context_2** should exist as a second summary (and where used).
- **Questions for you:**
  1. Is **context_1 = context_short** (AI summary) sufficient, or do you also want **raw transcript** stored on session for report evidence?
  2. Do you want **context_2** as an AI summary of recording_2 (like context_short for recording_1)? If yes, we add e.g. `session.context_short_2` or `session.context_2`.
  3. Retention / consent: do you want schema and logic for “store transcript until X” or “user consented at Y”?

---

## 5) Metric_questions integration

### Answered from code

- **Static vs dynamic:** Questions come from **v2_metric_questions** (positions 1–3). Same **3** questions for all users in the flow; not varied by focus_task or score_1. (Admin can edit the global pool.)
- **Role:** Used **only** for **task generation** (the 2-sentence final task). Not used for gating, not used for focus selection, not used in score_1 or score_2. They are “self-ratings” / goals that get woven into the generated instruction.
- **Versioning:** No question_version_id; if admin edits a question, future sessions get the new text. Past sessions keep stored `metric_answers` (and snapshot in session: `session_metric_question_1/2/3` for report).

### You decide

- **Gap:** Question bank versioning + explicit “which questions when” + whether answers should ever affect scoring or focus.
- **Questions for you:**
  1. Should metric_questions ever **vary** by focus_task or score_1 (e.g. different questions for different levels)?
  2. Do you want a **version** or snapshot of the question set stored per session for reproducibility?

---

## 6) AI task generation “framework”

### Answered from code

- **Output:** Single **string** (2 sentences). No JSON, no steps, no success criteria stored. Format is fixed in prompt: (1) “Based on [context], your task is [focus_task].” (2) “Focus especially on [answer_1], [answer_2], [answer_3].”
- **Constraints:** Prompt says “20–50 words total”, “no extra commentary”. No explicit validation step; we don’t check length or content after generation.
- **Reproducibility:** We do **not** store prompt + model + params. So we can’t replay the same task generation.
- **Rubric alignment:** The generated task is narrative only; score_2 is computed from the same 5 metrics (pace, strength, fillers, emotion, keywords). No explicit “task spec” that score_2 is checked against.

### You decide

- **Gap:** TaskSpec schema, validation rules, optional versioning of prompt/model.
- **Questions for you:**
  1. Do you want the generated task stored on the session (e.g. `final_task_text`) for history and reproducibility?
  2. Do you want **validation** (e.g. non-empty, length 20–50 words, no forbidden content) and retry or fallback if validation fails?
  3. Do you need a **structured** output (e.g. JSON with steps + success criteria) instead of one string? If yes, define the schema (TaskSpec).

---

## 7) score_2 vs score_transcription

### Answered from code

- **score_2:** Computed by **compute_metrics_v2**: 5 metrics (pace, strength, fillers, emotion_achieved, keywords_used). Uses **transcript** (for pace via WPM, fillers, keywords) and **audio**-derived strength where available; emotion from post-recording “emotion_achieved_check” answer. So score_2 is already partly transcript-based.
- **score_transcription:** **Not implemented.** The name doesn’t appear in code. So the “how to calculate?” is open.

### You decide

- **Gap:** Define **score_transcription** so it doesn’t double-count with score_2.
- **Suggested split (you confirm or change):**
  - **score_2** = delivery/performance rubric (pace, strength, fillers, emotion, keywords) — **keep as is.**
  - **score_transcription** = something **different**, e.g.:
    - **Option A:** Task adherence / “did they do the task?” (e.g. LLM or rules: does transcript match the generated task intent?).
    - **Option B:** Textual quality (coherence, clarity) separate from delivery.
    - **Option C:** Drop score_transcription and keep only score_2; use report narrative for “did they follow the task?”
- **Questions for you:**
  1. Do you want **score_transcription** at all? If yes, which option (A/B) or another definition?
  2. If yes, where is it stored (session only, or also on recording) and is it included in **score_end**?

---

## 8) After_recording_questions

### Answered from code

- **Type:** They are **reflective** (e.g. “Did you achieve the intended emotion?”, “How was this recording?”, “Any reflection?”). Not used as factual difficulty/confidence in scoring.
- **Influence:** Answers are passed into **generate_final_report** as `post_answers` and into **compute_metrics_v2** for the **emotion_achieved** metric (only the one with `code == "emotion_achieved_check"`). So one question directly affects score_2; the rest only affect report narrative.
- **Mandatory:** Backend does **not** require all questions to be answered. We match submitted answers to `post_question_ids`; missing answers simply don’t appear in the report. So effectively **optional** from backend perspective. **Frontend** can enforce “must answer all” if you want.

### You decide

- **Gap:** Required vs optional and behavior when some are skipped.
- **Questions for you:**
  1. Should **all** post-recording questions be **required** before report generation? If yes, backend can reject submit until all are answered (we’d need to define “all” from session’s post_question_ids).
  2. Should **missing** answers be mentioned in the report (e.g. “Question X was not answered”)?

---

## 9) report_history: score_end + context_end

### Answered from code

- **score_end:** **Implemented** as `(performance_score_1 + performance_score_2) / 2`, clamped to [0, 1]. Stored on session. Used for **next** warm-up selection (last score). No score_transcription, no confidence, no improvement delta in the formula.
- **context_end / report:** **Implemented** as `generate_final_report(...)` output. Stored in `v2_reports.report_text` and appended to `session.context_long_entries`. Report uses: transcript (recording_2), post_answers, context_short (context_1), metric_answers, performance_score_1/2, admin_context. No fixed “evidence snippet” schema; model produces free text (with a 3-paragraph homework rubric in prompt). No explicit “actionable next steps” structure in schema.

### You decide

- **Gap:** score_end formula (keep or add score_transcription / improvement), report schema, evidence strategy.
- **Questions for you:**
  1. Keep **score_end = (score_1 + score_2) / 2**, or add **score_transcription** (e.g. weighted average of 3)?
  2. Should **context_end** have a **fixed structure** (e.g. “Summary / Evidence / Next steps”) or stay free-form?
  3. Do you want **evidence snippets** (e.g. quote transcript in report) or only narrative?

---

## 10) Admin feedback loop

### Answered from code

- **When changes take effect:** **Next session only.** Admin edits (overrides, speaker_profile, task/question CRUD) are persisted in DB; the **next** time the user starts or loads a session, they see the new data. No “mid-session” sync; if user is in the middle of a run, they keep the current session state until they finish or abandon.
- **Re-scoring past sessions:** **Not implemented.** Admin cannot today “adjust scoring” for a past session. Report text can be **edited** (PATCH session report: append/replace entries). So **no** retroactive re-score; scores are **forward-only** for past sessions.
- **Audit trail:** **Not implemented.** No log of “who changed what, when” for admin edits.
- **student_context:** Two places exist: (a) **v2_speaker_profiles** (coach_notes, main_goal, etc.) — admin-editable; (b) **get_user_admin_context** = professional_notes + report_tech + specific_questions (different tables). Report uses (b). **Ownership:** coach-only; user does not see these in the current API. So “student_context” is effectively **admin/coach-provided** for report and context.

### You decide

- **Gap:** Change management (versioning, audit, retroactive re-score).
- **Questions for you:**
  1. Do you want **audit logging** for admin edits (who, when, what table/row)?
  2. Should admin be able to **override** performance_score_1, performance_score_2, or performance_score_end for a session (e.g. for corrections)? If yes, we need a place to store override (session or report) and API.
  3. Unify “student_context” to a **single** concept (e.g. merge speaker_profile + professional_notes for report) and name it clearly in API?

---

## 11) State machine / lifecycle

### Answered from code

- **States are implemented.** `v2_sessions.status`: `warm_up` → `task_block` → `final_task_ready` → `post_questions` → `completed`. Transitions: recording_1 → task_block; metric_answers → final_task_ready; recording_2 → post_questions; post_answers → completed. So we have a linear state machine; no branch for “admin_reviewed” or “abandoned” in the same enum (you could add them).
- **Partial completion:** Supported. User can stop at any step; session remains in that status. Resume uses same session and same status.
- **Idempotency:** Upload endpoints (recording_1, recording_2) create one recording per call; duplicate submits would create duplicate recordings unless frontend prevents double-submit. So **frontend** should prevent double-submit; backend could add idempotency keys if you want.

### Frontend vs backend

- **Frontend:** “Which step am I on?” = drive UI from `session.status` (and possibly from “do I already have recording_1_id?” etc.). Retry/abandon UX (e.g. “Start over”, “Resume”) is frontend; backend just exposes session and status.
- **You decide:** Do you want an explicit **abandoned** or **admin_reviewed** status and transitions (e.g. admin marks “reviewed”)? If yes, we add the status and a PATCH or POST to transition.

---

## 12) QA / anti-cheat

### Answered from code

- **Not implemented.** No minimum duration, silence detection, plagiarism/reading detection, or off-topic check. No QC gates that block progression. Report and task generation use OpenAI without a formal “hallucination check.”

### You decide

- **Gap:** QC gates (min duration, silence, etc.) and what happens when they fail (block vs warn vs allow).
- **Questions for you:**
  1. **Minimum audio duration** (e.g. 30 s)? If below, reject upload or warn?
  2. **Silence detection** (e.g. reject if > X% silence)?
  3. Any **content** checks (off-topic, reading from script) — and if so, block or flag in report?

---

## Summary: “Must-define” short list

| # | Gap | Answered in code? | Your decision needed |
|---|-----|-------------------|----------------------|
| 1 | Session/Attempt + versioning | Session exists; no version IDs | Version IDs for tasks/metrics/prompts? warm_up_task_id on session? |
| 2 | Scoring spec | 0–1, average, partial fallbacks | Weights? Fallback when transcript fails? Store evidence on session? |
| 3 | Focus selection | Rule + random tie-break; no match → None | No-match behavior? Tie-break policy? Use metric_questions for focus? |
| 4 | Transcript/context | context_1 = summary; context_2 = raw only | context_2 as summary? Retention/consent? |
| 5 | Metric_questions | Static 3; used only for task gen | Vary by focus/score? Version per session? |
| 6 | AI task framework | 2-sentence string; no validation/version | Store final_task_text? Validation? TaskSpec JSON? |
| 7 | score_transcription | Not implemented | Define (adherence vs quality vs drop); include in score_end? |
| 8 | After_recording required? | Optional in backend | Require all? Mention missing in report? |
| 9 | score_end + report schema | (s1+s2)/2; free-form report | New formula? Fixed report structure? Evidence snippets? |
| 10 | Admin edits | Next session; no audit; no score override | Audit log? Override scores? Unify student_context? |
| 11 | State machine | 5 states; linear | Add abandoned/admin_reviewed? Idempotency keys? |
| 12 | QC gates | None | Min duration? Silence? Content checks? |

---

## Definitely frontend-only (no backend contract change)

- **“Which step am I on?”** — Derive from `session.status` + optional `recording_1_id` / `recording_2_id` presence. Backend already returns these.
- **Retry / abandon / “Start over”** — UX and when to call “start new session” vs “resume”; backend already supports resume. “Start over” could be “create new session” (backend already has session start).
- **Preventing double-submit** — Disable button after submit, or use a client-side “submitted” flag. Optional: backend idempotency key later.
- **Showing “No focus task available”** — When task_block returns focus_task: null, frontend shows message. Backend can add explicit error when no task matches (currently returns null).
- **Mandatory post-questions UX** — Frontend can block “Submit” until all questions answered; backend can optionally enforce same.

Use this doc to answer the reviewer’s gaps: copy “Answered from code” where applicable, and fill “You decide” / “Questions for you” with product decisions. Once you answer the questions, the same doc can drive implementation and a precise end-to-end flow diagram.
