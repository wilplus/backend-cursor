# Homework flow & performance — single reference

This document is the single reference for: how performance scores are calculated, how the task (focus task + final task text) is generated, the homework flow (status-driven; steps can be skipped), the frontend contract (status, applyStatusToState, GET/abandon/refresh), backend invariants, coaching memory, and troubleshooting.

---

## 1. Performance calculation (step by step)

All scores are in the range **0–1**. The student-facing “KPI” is **`performance_score_end`**.

### 1.1 performance_score_1 (after recording 1)

**When:** Background job after **POST recording-1** (`services/recording_1_job.py`).

**Inputs:**

- **WPM** from transcript length and duration.
- **Filler count** from `count_fillers(transcript)`.
- **Strength:** not from audio in this job → `strength_raw = None` → strength component fixed at **0.5**.

**Formula** (`services/metrics_v2.compute_performance_score_1`):

- `pace_n` = `normalize_pace(wpm)` — 120–160 WPM → 1.0; below/above → smooth decay (60–220 range).
- `strength_n` = 0.5 (no audio strength in recording-1).
- `fillers_n` = `normalize_fillers(filler_count)` — ≤3 fillers → 1.0; more → smooth decay (cap 15).

```text
performance_score_1 = (pace_n + strength_n + fillers_n) / 3
performance_score_1 = clamp(performance_score_1, 0, 1)
```

**Stored:** On **session** as `performance_score_1`. Used for focus-task selection.

---

### 1.2 performance_score_2 (after recording 2)

**When:** During **POST recording-2** (preliminary) and again in **POST post-answers** (final).

**First pass (POST recording-2):** Uses WPM, filler_count, transcript; `emotion_achieved = False`; keywords from metric answer 1. Result stored on session and recording, returned in response.

**Second pass (POST post-answers):** Same inputs plus **emotion_achieved** from reflective question with code `emotion_achieved_check` (YES/Y/1/TRUE → true). **compute_metrics_v2** is called again; recording and session updated with final **performance_score_2**.

**Formula** (`services/metrics_v2.compute_metrics_v2`):

- `pace_n`, `strength_n`, `fillers_n` = same normalizers as score_1.
- `emotion_n` = 1.0 if emotion_achieved else 0.0.
- `keywords_n` = 1.0 if ≥2 of first 3 keywords appear in transcript (word boundary), else 0.0.

```text
performance_score_2 = (pace_n + strength_n + fillers_n + emotion_n + keywords_n) / 5
performance_score_2 = clamp(performance_score_2, 0, 1)
```

---

### 1.3 performance_score_end (final KPI)

**When:** **POST post-answers** handler, after final performance_score_2 is set.

**Formula** (improvement-weighted; recording 2 and improvement weighted higher):

```text
performance_score_1 = session.performance_score_1
performance_score_2 = final["performance_score"]   # from compute_metrics_v2 with real emotion/keywords

improvement = max(0, performance_score_2 - performance_score_1)

performance_score_end = 0.3 * performance_score_1 + 0.6 * performance_score_2 + 0.3 * improvement
performance_score_end = clamp(performance_score_end, 0, 1)
```

**Stored:** On **session** as `performance_score_end`. Returned in POST post-answers response; used for report, chart, coach email, warm-up selection, coaching memory. **Recording-1-only flow:** When Sniper data exists (`session_sniper_metrics.stage_score`), that value is used as the single end score (overwriting the metrics_v2-based value). The coach email “End score: X%” shows this same single score only.

---

### 1.3.1 Graph vs “metrics” / “my result” (must match)

**Problem:** If the UI shows 58% as “your result” but the history graph shows 70%, it’s because two different numbers are being used:

- **`scores.final`** (or **`performance_score_2`**) = raw average of the 5 metrics for recording 2 only (e.g. 0.58 → 58%). This is **not** the same as the end KPI.
- **`scores.overall`** (and **`performance_score_end`**) = improvement-weighted KPI (0.3×score_1 + 0.6×score_2 + 0.3×improvement). The **graph** (`performance_history`) uses this value for every bar.

**Fix:** Use **one** number everywhere for “your result” and for the graph: **`scores.overall`** (or **`performance_score_end`**). The canonical student-facing score is **`performance_score_end`**. Do **not** use `scores.final` as the main “your result” if the graph is driven by `performance_history` (which is based on `performance_score_end`), or the two will disagree.

---

### 1.4 Constants (metrics_v2)

| Constant | Value | Use |
|----------|--------|-----|
| PACE_TARGET_LOW / HIGH | 120, 160 | WPM “optimal” band (score 1.0) |
| PACE_MIN / MAX | 60, 220 | Linear then smoothstep outside band |
| Strength center / radius | -25, 15 | dB for normalize_strength (when used) |
| Fillers “full” | ≤3 | fillers_n = 1.0 |
| Fillers decay | (10 - min(count,15))/10 | t for smoothstep |
| Keywords min_match | 2 | ≥2 of first 3 keywords → 1.0 |

**Legacy:** `scoring_service` and `performance_scores` table are **not** used in the homework flow. The single source of truth is `metrics_v2` + this formula.

---

## 2. Task generation (focus task + final task text)

The “task” the student sees on step 3 (final recording) is produced in two stages: (1) **focus task selection** after recording-1, and (2) **final task text generation** after metric-answers.

### 2.1 Context short (from recording 1)

**When:** Recording-1 background job (`services/recording_1_job.py`), after transcribing.

**What:** `openai_service.generate_context_short(transcript)` — 2–3 sentence summary of the warm-up (tone, pacing, main point). Model: gpt-4o-mini, ~150 tokens. If the call fails, the first 400 chars of the transcript are used.

**Stored:** On **session** as `context_short`. Used later as input to final-task text generation.

### 2.2 Focus task selection (after recording 1)

**When:** Same recording-1 job, after `performance_score_1` and `context_short` are computed.

**Steps:**

1. **Per-student tasks:** `db.v2_select_student_focus_task_for_score(user_id, performance_score_1)`:
   - Loads the student’s **v2_focus_tasks** (assigned by admin or synced from pool).
   - **Eligible:** tasks where `max_performance_score >= performance_score_1` (score band).
   - **Anti-repeat:** Excludes tasks in `recent_focus_task_ids` from coaching memory (up to 5), or last 2 completed sessions’ `selected_task_id` if no memory.
   - **Multi-factor (optional):** If coaching memory has `recurring_issues` (e.g. `["too_fast", "high_fillers"]`) and any task has `targets` (e.g. `["pacing"]`, `["fillers"]`), `score_and_pick_focus_task` scores candidates by weakness match (RECURRING_ISSUE_TARGETS: too_fast/too_slow → pacing, high_fillers → fillers) and picks the best; tie-break = first by order_index.
   - Returns one task as `{ id, title, prompt_text }` (both title and prompt_text from the task’s `text`).

2. **Fallback if no per-student tasks:** `v2_flow_service.select_focus_task_for_performance_score_1(all_tasks, performance_score_1, assigned_task_ids)` — uses **v2_tasks** (global pool), `min_task_score <= performance_score_1`, optional `assigned_next_task_ids` filter; if none match, picks easiest (smallest min_task_score).

3. **Fallback if still none:** `{ id: null, title: DEFAULT_FOCUS_TASK_TEXT, prompt_text: DEFAULT_FOCUS_TASK_TEXT }` — default text is **"Pay attention to your breathing"** (`db.DEFAULT_FOCUS_TASK_TEXT`).

**Stored:** On **session** as `selected_task_id` (and on recording as `task_id`). The task’s `title` / `prompt_text` are not stored here; they are read again at final-task generation time via `db.v2_get_task_or_focus_task(selected_task_id)`.

### 2.3 Final task text (after metric-answers)

**When:** **POST metric-answers** (`routes/homework.py`), after the recording-1 job has completed (session has `context_short` and `selected_task_id`). If the job failed, fallback uses empty context and default focus task.

**Inputs:**

- **context_short** — from session (recording-1 job).
- **focus_task** — from `db.v2_get_task_or_focus_task(session.selected_task_id)` → `title` and `prompt_text` (or default).
- **metric_answer_1, metric_answer_2, metric_answer_3** — from the request body (student’s answers on step 2).

**Generation** (`openai_service.generate_final_task`):

- **Sanitization:** Context capped 500 chars; each metric answer trimmed and capped at 8 words (`_sanitize_metric_answer`); focus task string = `title + " " + prompt_text`, capped 200 chars.
- **LLM:** gpt-4o-mini, JSON output with `sentence1` and `sentence2`. System prompt requires: sentence1 starts with “Based on”, sentence2 with “Focus especially on”; 20–50 words total; no “60 seconds”, “minutes”, “short summary”, “final recording”. User prompt injects context, focus task, and the three metric answers as data.
- **Validation:** `_validate_final_task_output` — exactly 2 sentences; word count 20–55; “based on” and “focus especially on” present; each non-empty metric phrase must appear verbatim (case-insensitive). Forbidden phrases rejected.
- **Retry:** If the first call’s JSON is invalid or fails validation, one retry with a repair prompt.
- **Fallback:** If both fail, deterministic string: `"Based on {context_short}, your task is: {focus_task}. Focus especially on {metric_1}, {metric_2}, {metric_3}."` (or “your self-ratings” if no metrics).

**Stored:** On **session** as `final_task_text`. Returned in POST metric-answers response as `final_task` (the string the frontend shows on step 3).

### 2.4 Summary flow

```text
Recording 1 job:
  transcript → generate_context_short → context_short (session)
  performance_score_1 → v2_select_student_focus_task_for_score (or fallbacks) → selected_task_id (session)

POST metric-answers:
  context_short + selected_task_id → v2_get_task_or_focus_task → focus title/prompt
  + answer_1, answer_2, answer_3
  → generate_final_task (LLM or fallback) → final_task_text (session), returned as final_task
```

---

## 3. Homework flow (status-driven; steps can be skipped)

The flow is **status-driven**. The backend does **not** require a strict 0→5 sequence: status can jump (e.g. to `report_generating` or `completed` after recording-1 when there are no focus tasks, or from step 2 to report via POST complete-from-recording-1). Frontend should derive the displayed step from `status` and handle all status values (including skips).

### 3.1 Status vocabulary (public API)

Frontend must use **only** top-level `status`. Backend returns:

- `none` — no active session
- `recording_1_required` — step 1 (warm-up)
- `task_block` — step 2 (metric questions)
- `final_task_ready` — step 3 (final recording)
- `post_questions` — step 4 (reflective questions)
- `report_generating` — report being generated from recording 1 only (poll until `completed`)
- `completed` — step 5 (report)

Mapping to step: none→0, recording_1_required→1, task_block→2, final_task_ready→3, post_questions→4, report_generating→show “report generating” then poll, completed→5.

### 3.2 Endpoints

| Step | Action | Endpoint | Response includes |
|------|--------|----------|-------------------|
| 0→1 | Start | POST `/v2/homework/session/start` | `status`, `session_id`, `warm_up_task` |
| 1→2 | Upload recording 1 | POST `.../session/<id>/recording-1` | `status: "task_block"`, `task_block`, `recording_id` |
| 2→3 | Submit metric answers | POST `.../session/<id>/metric-answers` | `status: "final_task_ready"`, `final_task` |
| 3→4 | Upload recording 2 | POST `.../session/<id>/recording-2` | `status: "post_questions"`, `recording_id`, `performance_score_2` |
| 4→5 | Submit post-answers | POST `.../session/<id>/post-answers` | `status: "completed"`, `report_text`, `performance_score_end` |
| Any | Abandon | POST `.../session/<id>/abandon` | 200 deleted, 404 already gone |
| Cold load | Status | GET `/v2/homework/session/status` | `status`, `session_id`, `session`, `has_active_session`, `warm_up_task` (when applicable) |

GET status does **not** return `task_block`, `final_task`, or `report_text`; those come from the mutation that advances to that step.

### 3.3 Database and BFF

**Migrations (run in order in Supabase SQL Editor):** `migrations/v2_all_in_one.sql` → coaching migrations (see architecture rule) → `add_tutor_feedback_deadline.sql` → `add_tutor_feedback_sent_at.sql`. After new columns: **Supabase → Settings → API → Reload schema cache**.

**BFF (Next.js):** Session-scoped routes must use **synchronous params** (e.g. `{ params }: { params: { sessionId: string } }`), not `Promise<...>`, or production can 404. Reference: `docs/homework-bff-routes/session/[sessionId]/`. Forward backend response body unchanged (do not strip `status` or rename `report_text`).

### 3.4 UI per step

- **Step 0:** GET status; if no active session, call POST start. Show tutor_feedback_message when present (no active session, tutor not yet sent feedback).
- **Step 1:** Warm-up text from status/start; record; use **recording-1 response only** to advance to step 2 (do not call GET status after recording-1 to set step).
- **Step 2:** Show `task_block` from recording-1 response. If on step 2 after refresh with no task_block, fetch GET task-block or build from `session.session_metric_question_1/2/3`. Abandon button (POST abandon → applyStatusToState({ status: "none" })). On 409 RECORDING_1_PROCESSING, show message and optionally poll GET status only to decide when to retry POST metric-answers; step advances only when POST metric-answers succeeds.
- **Step 3:** Show `final_task` from metric-answers response; record 2 (60–300 s); advance from recording-2 response.
- **Step 4:** If no reflective questions, POST post-answers with `answers: []`; else show questions, submit, then use post-answers response for step 5.
- **Step 5:** Show report from post-answers response (`report_text`, `performance_score_end`). No GET status needed (completed sessions not returned by status).

---

## 4. Frontend contract

### 4.1 Principles

- **Backend is the single source of truth.** Derive the displayed step from `status` only. The flow can skip steps (e.g. 1→report when no focus tasks, or 2→report via complete-from-recording-1); do not force a strict 0→5 order.
- **Each step transition is driven by the mutation response or GET status.** Do not assume step N+1 always follows step N.
- **GET status on cold load** (mount, refresh, tab refocus) and when polling (e.g. for `report_generating`). Do not call GET status inside a mutation handler only to “fix” step; use the mutation response.

### 4.2 applyStatusToState

- Single function: `applyStatusToState(res: HomeworkResponse)`.
- Step from `mapStatusToStep(res.status)` only. No floors, caps, Math.max, or refs.
- When `status === "none"`: full reset (step 0, clear session and step-specific state).
- Other fields (session_id, warm_up_task, task_block, final_task, report_text, performance_score_2, performance_score_end) set only when present in `res`. Use `res.report_text` (backend sends `report_text`, not `report`).
- **Step from status only:** If GET returns `status: "task_block"`, render step 2 even if task_block payload is missing (handle via Option A or B below). If status is `completed` or `report_generating`, show report or “generating” accordingly; do not force a lower step.

### 4.3 Refresh strategy

- **Option A:** Backend extends GET status with step payload when relevant (task_block, final_task, report_text). Then GET alone suffices for resume.
- **Option B:** GET returns only status/session_id/session/has_active_session/warm_up_task. On refresh, set step from status; if step-specific data missing, show “Resuming…” or re-fetch/derive from session. **Never** reset to step 1 because payload is missing.

### 4.4 Abandon

- Call POST abandon. On 200 or 404, run `applyStatusToState({ status: "none" })`. Do not call GET after abandon.
- Treat 404 as success (session already gone).

### 4.5 RECORDING_1_PROCESSING polling

- When POST metric-answers returns 409 RECORDING_1_PROCESSING, frontend **may** poll GET status until recording-1 is done, then retry POST metric-answers.
- This GET is **only** to decide when to retry; **do not** pass the GET response to `applyStatusToState`. Step advances only when POST metric-answers succeeds; then call `applyStatusToState(retryResponse)`.

---

## 5. Backend invariants

### 5.1 Session and status

- **GET status:** Direct DB read (`v2_get_active_homework_session`); no caching. Returns 200 with `status`, `session_id`, `session`, `has_active_session`; when no session, `status: "none"`, `session: null`.
- **In-app expiry by age:** Disabled. `v2_session_expired()` always returns False. Incomplete sessions persist until user abandons or completes. Optional: `run_cleanup_v2_sessions.py` (cron) can delete old incomplete sessions.
- **No automatic advance:** No background job or side effect moves session from `task_block` to `final_task_ready` without an explicit POST metric-answers.

### 5.2 Abandon

- **POST `/v2/homework/session/<id>/abandon`:** 200 when session deleted; 404 when session not found. Never 500 for “session not found” (use 404). Same auth as other homework routes.

### 5.3 Session gone / 404

- Session-scoped endpoints (metric-answers, recording-2, post-answers, etc.) return **404** with `code: "SESSION_NOT_FOUND"` when the session does not exist.
- Frontend should treat 404 as “session gone” and reset to step 0 (e.g. `applyStatusToState({ status: "none" })`), not show a dead-end error.
- If GET status returns a session_id but a later request returns 404, the row may have been deleted after status ran (abandon, cleanup, or another tab). Frontend: on any 404 from session-scoped call, reset to step 0.

---

## 6. Coaching (summary)

- **v2_student_coaching_memory:** Updated on session completion (`v2_upsert_student_coaching_memory`). Holds `last_5_scores`, `recent_focus_task_ids`, `recurring_issues` (from last 5 sessions’ `recording_1_performance_profile`: e.g. too_fast in ≥3 of 5 → `"too_fast"`).
- **recording_1_performance_profile:** Set by recording-1 job. Shape: `{ "version": 1, "pace_level": "too_slow"|"optimal"|"too_fast", "filler_level": "low"|"medium"|"high" }`. Thresholds: pace &lt;110 / &gt;170, fillers ≤3 / 4–8 / &gt;8.
- **Focus task selection:** `v2_select_student_focus_task_for_score(user_id, performance_score_1)` uses score band, excludes recent focus task IDs from memory, and when `recurring_issues` and task `targets` exist uses multi-factor scorer (e.g. too_fast → prefer pacing tasks).

---

## 7. Step 0: tutor feedback message

When user has **no active session** and recently completed a lesson (coach has not yet sent feedback), GET status can include:

- **tutor_feedback_deadline:** ISO 8601.
- **tutor_feedback_message:** User-facing string, e.g. “Your coach has until … to review your last lesson and send you new homework.”

Frontend: on step 0, if `tutor_feedback_message` is present, show it in an info banner. Omitted when user has active session, never completed, or coach already sent feedback.

---

## 8. Default warm-up

- **Backend:** Creates default warm-up “How was your day so far?” for users with none. API returns `warm_up_task: { id, text }` from start/status.
- **Frontend:** If warm-up is missing or empty, show **“How was your day so far?”** so the flow never blocks. On 422 `NO_WARMUP_CONFIGURED`, show message and step 0 (contact coach).

---

## 9. Troubleshooting

### 9.1 Post-answers 500 / PGRST204 (completed_at missing)

- **Symptom:** 500 on POST post-answers, “Could not find the 'completed_at' column of 'v2_sessions'”.
- **Fix:** Run `migrations/add_tutor_feedback_deadline.sql` in Supabase; reload PostgREST schema cache (Settings → API → Reload schema cache).

### 9.2 PGRST205 (v2_student_coaching_memory missing)

- **Symptom:** 500 on first “See my report” (retry may then return report).
- **Fix:** Run `migrations/add_v2_student_coaching_memory.sql` and `add_recurring_issues_to_coaching_memory.sql` if used; reload schema cache. Backend catches coaching-memory upsert failures and still returns the report, but run migrations for correct behavior.

### 9.3 Metric questions step (step 2) stuck

- **409 RECORDING_1_PROCESSING:** Backend not ready until recording-1 job has set `performance_score_1` and `context_short`. Show backend message; optionally poll GET status to decide when to retry POST metric-answers (do not use GET response to set step).
- **422 VALIDATION_ERROR:** Require answers for all questions with text in task_block; show backend message.
- **No questions:** Ensure metric questions exist in admin (v2_metric_questions, positions 1–3). On refresh at step 2, build task_block from `session.session_metric_question_1/2/3` or GET task-block.

### 9.4 Session gone (404)

- **Abandon returns 404:** Treat as success; clear state and go to step 0.
- **GET status returns no active session:** Clear state and go to step 0; show short message (“Session was cleared. You can start a new one.”).
- **Any session-scoped endpoint returns 404:** Treat as session gone; reset to step 0 (e.g. `applyStatusToState({ status: "none" })`).

### 9.5 BFF 404 on session routes

- Ensure dynamic routes use **synchronous params** (e.g. `params: { sessionId: string }`), not `Promise<...>`. Reference: `docs/homework-bff-routes/session/[sessionId]/`. Redeploy and clear cache if needed.

---

## 10. Migration order (quick reference)

1. `migrations/v2_all_in_one.sql`
2. Coaching migrations: `add_v2_student_coaching_memory.sql`, `add_recording_1_performance_profile.sql`, `add_recurring_issues_to_coaching_memory.sql`, `add_focus_task_targets_and_difficulty.sql`
3. `add_tutor_feedback_deadline.sql`, `add_tutor_feedback_sent_at.sql`
4. Reload schema cache in Supabase

---

**Related:** Architecture and layout are in `.cursor/rules/architecture-taskmaster.mdc`. Admin API contract: `docs/frontend-admin-panel/API-POOL-CONTRACT.md`.
