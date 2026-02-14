# Implementation plan: Fast POST recording-1 + background processing

**Goal:** Return quickly from POST recording-1 with a task_block so the user sees the metric-questions step (step 2) immediately, while heavy work (transcribe, score, context, focus task) runs in a background job. No change to the HTTP contract from the client’s perspective except optional `recording_1_processing` and new 409 codes for metric-answers.

---

## 1. Principles

- **Fast path:** POST recording-1 validates, stores audio (or path), creates minimal recording row, sets session to `task_block`, returns `task_block`. No transcription or AI in the request.
- **Background job:** All heavy, failure-prone work (transcribe, WPM/fillers, performance_score_1, context_short, focus task, signed URL, full recording + session update) runs in a job.
- **Semantics:** `status = task_block` means “user is on step 2.” “Ready for metric-answers” means `status == task_block` **and** `performance_score_1` and `selected_task_id` are set (or processing has explicitly failed).
- **Single source of truth for readiness:** Use a helper `is_recording_1_ready(session)` so metric-answers and any other caller check one place.

---

## 2. Schema and processing status

- **Where to store processing status:** On the **session** (simplest: metric-answers already loads the session). Add a column such as:
  - `recording_1_processing_status` with values `'pending' | 'completed' | 'failed'`.
- **Consistency:** All checks for “is recording-1 done?” use this plus `performance_score_1` / `selected_task_id`. No mixing session vs recording for this decision.
- **Optional:** `recording_1_error_code` or `recording_1_error_message` on session for logging/support when status is `'failed'`.

---

## 3. Backend

### 3.1 POST recording-1 (fast path)

**Stays in the handler:**

- Auth, load session; 404 if missing. Require `status == STATUS_WARM_UP`; 409 otherwise.
- **Multipart:** Upload audio to storage → get `storage_path`. Do **not** transcribe. Get `duration_seconds` from form if present, else `None` for the job.
- **JSON (direct-to-storage):** Validate `storage_path` and `duration_seconds`. Idempotency: if session already has `recording_1_id` and that recording has the same `storage_path`, return 200 with existing `recording_id`, `task_block`, and `performance_score_1` if set; do not enqueue again.
- Create **minimal recording row:** `user_id`, `session_v2_id`, `storage_path`, `duration_seconds` (if known). Omit transcript, WPM, task_id, audio_url, etc.
- Update session: `recording_1_id`, `status = STATUS_TASK_BLOCK`, `recording_1_processing_status = 'pending'`. Do **not** set `performance_score_1`, `context_short`, `selected_task_id`.
- Build `task_block` via `v2_get_metric_questions_for_flow()`.
- Enqueue job with `(session_id, recording_id, storage_path, user_id, duration_seconds)`. Deduplicate by `recording_id` (or session) so the same recording is not enqueued twice.
- Return 200 with `recording_id`, `task_block`, and optionally `recording_1_processing: true`. Omit `performance_score_1` in the fast response (or send null).

**Moves to the job:** Everything else (download, transcribe, WPM/fillers, score, context_short, focus task, signed URL, full recording update, session update with score/context/selected_task and `recording_1_processing_status = 'completed'`; on failure set `recording_1_processing_status = 'failed'`).

### 3.2 Background job

- **Start of job:** Load session by `session_id` and `user_id`. If no session (e.g. abandoned/deleted), log and return; do not update.
- Download audio from `storage_path`.
- Transcribe; set `duration_seconds = transcript_result.get("duration") or payload.duration_seconds`.
- Compute WPM, fillers, `performance_score_1`; generate `context_short`; select focus task (same logic as current handler).
- Update recording row with full details; update session with `performance_score_1`, `context_short`, `selected_task_id`, `recording_1_processing_status = 'completed'`.
- On exception: set `recording_1_processing_status = 'failed'` (and optional error code/message), log and Sentry; do not set score/context/task.

### 3.3 Readiness helper

- **`is_recording_1_ready(session)`** (or equivalent): returns true iff  
  `session["status"] == "task_block"` and  
  `session.get("performance_score_1") is not None` and  
  `session.get("selected_task_id") is not None` and  
  `session.get("recording_1_processing_status") == "completed"` (or omit if not yet added; then “not failed and score/task set”).
- Use this in metric-answers and anywhere that needs to know “can we proceed to generate final_task?”

### 3.4 POST metric-answers

- After requiring `status == STATUS_TASK_BLOCK` (and idempotency for already final_task_ready):
  1. If **ready** (e.g. `is_recording_1_ready(session)`) → proceed as today (generate final_task, update session).
  2. If **failed:** `recording_1_processing_status == 'failed'` → return **409** with `code: "RECORDING_1_FAILED"`, message e.g. “We couldn’t analyze your recording. Please try again or contact support.” Do not poll.
  3. Else (still pending or stuck) → return **409** with `code: "RECORDING_1_PROCESSING"` (or `"RECORDING_1_STUCK"` for restart cases), message “Your recording is still being analyzed. Please wait a moment and try again.” Frontend may poll and retry.
- **Optional re-enqueue:** When detecting “stuck” (task_block, recording_1_id set, no score, not failed), re-enqueue the job **at most once per recording** (e.g. set a “re_enqueue_attempted” or check a flag on the recording/session so repeated metric-answers calls don’t spam the queue).

### 3.5 Polling endpoint

- The frontend needs a **stable endpoint** to poll to see when `performance_score_1` / `selected_task_id` are set. Use existing **GET /v2/homework/session/status** (or GET session by id if available). Ensure the response includes:
  - `session.performance_score_1`
  - `session.selected_task_id`
  - `session.recording_1_processing_status` (so the client can distinguish pending vs failed without guessing).

---

## 4. Duration source of truth

- Client may send `duration_seconds` in the fast path → use for minimal recording row and pass to the job.
- In the job: `duration_seconds = transcript_result.get("duration") or payload.get("duration_seconds")`. Use this single value for WPM, DB, and downstream. Do not have other code read “preliminary” duration from the minimal recording row as authoritative before the job finishes.

---

## 5. Option A (in-process queue) and restarts

- In-memory queue is lost on process restart → sessions can be stuck: `task_block`, `recording_1_id` set, no `performance_score_1`.
- **Mitigation:** metric-answers returns 409 RECORDING_1_PROCESSING (or RECORDING_1_STUCK) when this is detected; optionally re-enqueue **once** per recording (see 3.4). Optionally a cron/maintenance job to find such sessions and re-enqueue or log. At minimum: log distinctly (e.g. RECORDING_1_STUCK) so it’s visible.

---

## 6. Frontend

- **Use POST response immediately:** No change; advance to step 2 and set task_block from the response (which now returns quickly).
- **Optional:** If backend sends `recording_1_processing: true`, show “Analyzing your recording…” until GET status shows score/task or failed.
- **On metric-answers 409 RECORDING_1_PROCESSING:** Keep answers in state; show toast; disable Continue, show spinner; poll GET status every 2–3 s; when `performance_score_1` / `selected_task_id` present, re-POST metric-answers with same answers (or re-enable Continue). Cap polling (e.g. 30–60 s), then show “taking longer than usual.”
- **On metric-answers 409 RECORDING_1_FAILED:** Do not poll; show “We couldn’t analyze your recording” and optionally “Try again” (e.g. back to step 1 or re-record).

---

## 7. Implementation checklist

- [ ] Schema: add `recording_1_processing_status` (and optional error field) on session.
- [ ] Fast path: refactor POST recording-1 to store only, create minimal recording, set task_block + pending, enqueue job, return task_block.
- [ ] Job: implement worker (in-process Option A first): download, transcribe, score, context, focus task, update recording + session; session check at start; set completed/failed.
- [ ] Helper: `is_recording_1_ready(session)` and use in metric-answers.
- [ ] Metric-answers: add branches for RECORDING_1_PROCESSING and RECORDING_1_FAILED; optional re-enqueue once per recording.
- [ ] GET status (or session): ensure response includes `performance_score_1`, `selected_task_id`, `recording_1_processing_status` for polling.
- [ ] Frontend: handle 409 RECORDING_1_PROCESSING (poll, retry, cap) and RECORDING_1_FAILED (no poll, message + try again).
- [ ] Idempotency: same storage_path → 200 with existing data, no duplicate enqueue; job dedup by recording_id.
- [ ] Duration: job uses transcript duration when available, else client value; single value for all downstream.

This plan is the single reference for the recording-1 async refactor and incorporates the addendum and final refinements (processing status on session, readiness helper, polling contract, re-enqueue guard).
