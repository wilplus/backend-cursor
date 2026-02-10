# Student homework flow: structure, storage, and variables

## 1. Flow structure (5 steps)

| Step | UI name        | Backend status       | Allowed actions |
|------|----------------|----------------------|------------------|
| 1    | Warm-up task   | `warm_up`            | GET warm-up-task, POST recording-upload-url (recording "1"), POST recording-1, POST recording-metrics-chunk |
| 2    | Metric answers | `task_block`         | GET task-block, POST metric-answers, POST recording-metrics-chunk |
| 3    | Final task     | `final_task_ready`   | POST recording-upload-url (recording "2"), POST recording-2, POST recording-metrics-chunk |
| 4    | Questions      | `post_questions`     | GET questions, POST post-answers |
| 5    | Report / done  | `completed`          | (idempotent POST post-answers returns existing report) |

**Single source of truth for “current step”:** GET **session/status** → **`session.status`**. Map status to step: warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5.

---

## 2. Where things are stored

### Table: `v2_sessions` (one row per homework attempt)

| Column / field | Purpose | Set when |
|----------------|--------|----------|
| **id** | Session UUID. Used in URLs and as `session_id` / `session.id` in API responses. | On insert. |
| **user_id** | Owner of the session. | On insert. |
| **status** | Current step in the flow. **Source of truth for “which step”** (warm_up, task_block, final_task_ready, post_questions, completed). | Updated at each transition (see below). |
| **warm_up_task_id** | FK to `v2_warm_up_tasks`. Snapshot so resume shows same prompt. | Session start (or resume in warm_up). |
| **warm_up_task_text** | Snapshot of warm-up prompt text. | Session start (or resume in warm_up). |
| **session_metric_question_1/2/3** | Snapshot of the 3 metric question texts for this session. | Session start. |
| **recording_1_id** | FK to `recordings`. First recording (warm-up). | After POST recording-1. |
| **context_short** | AI summary of recording_1 transcript. Used to generate final_task. | After POST recording-1. |
| **performance_score_1** | Score for recording_1 (0–1, from strength/pace/fillers). | After POST recording-1. |
| **selected_task_id** | FK to `v2_tasks` (or focus task). Chosen from performance_score_1. | After POST recording-1. |
| **metric_answers** | JSONB: answer_1, answer_2, answer_3. | After POST metric-answers. |
| **final_task_text** | AI-generated final task prompt. | After POST metric-answers. |
| **recording_2_id** | FK to `recordings`. Second recording (final task). | After POST recording-2. |
| **performance_score_2** | Score for recording_2 (0–1, 5 metrics). | After POST recording-2. |
| **post_question_ids** | Array of post-recording question IDs for this session. | When GET questions is called. |
| **context_long** | Latest report text. | After POST post-answers. |
| **context_long_entries** | JSON array of report entries (with timestamps). | After POST post-answers (append). |
| **performance_score_end** | Final score (e.g. (score_1 + score_2) / 2). | After POST post-answers. |
| **created_at** | When the session was created. | On insert. |

**Status transitions (what updates `status`):**

- **warm_up** → **task_block**: POST recording-1 (sets recording_1_id, context_short, performance_score_1, selected_task_id, status).
- **task_block** → **final_task_ready**: POST metric-answers (sets metric_answers, final_task_text, status).
- **final_task_ready** → **post_questions**: POST recording-2 (sets recording_2_id, performance_score_2, status).
- **post_questions** → **completed**: POST post-answers (sets performance_score_end, context_long, context_long_entries, status).

### Table: `recordings`

| Column (main) | Purpose |
|---------------|--------|
| **id** | Recording UUID. Referenced by session.recording_1_id and session.recording_2_id. |
| **user_id** | Owner. |
| **session_v2_id** | Links to v2_sessions.id for homework flow. |
| **task_id** / **selected_task_id** | Focus task used for this recording (for recording_2). |
| **storage_path** | Path in Supabase Storage (e.g. audio_recordings bucket). |
| **duration** / **duration_seconds** | Length of audio. |
| **transcription_text** | Raw transcript. |
| **words_per_minute**, **filler_words_count** | Used for scoring. |
| **performance_score_v2**, **performance_metrics_v2** | Score and per-metric breakdown. |

Recording_1 and recording_2 are both rows in **recordings**; the session row points to them via **recording_1_id** and **recording_2_id**.

### Table: `v2_reports`

One row per completed homework session (created on POST post-answers). Stores report text and links to session and recording_2.

### Storage: Supabase bucket `audio_recordings`

Path pattern: **`{user_id}/{session_id}/{uuid}.webm`**. The session does not store this path; the **recordings** row stores **storage_path**. Backend returns `storage_path` and `bucket` from POST recording-upload-url; frontend uploads the blob to that path, then sends the same `storage_path` in POST recording-1 or recording-2.

---

## 3. API response shapes (what the frontend sees)

### GET session/status

- **session**: full `v2_sessions` row (includes id, status, warm_up_task_id, warm_up_task_text, recording_1_id, recording_2_id, context_short, performance_score_1, performance_score_2, selected_task_id, final_task_text, metric_answers, post_question_ids, context_long, performance_score_end, etc.).
- **session_id**: same as `session.id` (convenience top-level).
- **has_active_session**: true if there is an active session (status in warm_up, task_block, final_task_ready, post_questions).
- **warm_up_task**: { id, text } — from session snapshot or from v2_warm_up_tasks when status is warm_up.

**Frontend should use:** `session_id` or `session.id` for the session ID; **`session.status`** for the current step (and derive step 1–5 from it). Do not derive step from recording_1_id / recording_2_id when status is present; status wins.

### POST recording-1 response

- recording_id, performance_score_1, task_block (metric_question_1, metric_question_2, metric_question_3). After success, frontend should call GET session/status and apply that to state (step 2).

### POST metric-answers response

- final_task (text). After success, frontend should call GET session/status and apply that to state (step 3).

### POST recording-2 response

- recording_id, performance_score_2. After success, frontend should call GET session/status and apply that to state (step 4 or 5).

### POST post-answers response

- report_text, performance_score_end, performance_metrics, question analyses/scores. Session status becomes completed.

---

## 4. Variables summary (quick reference)

| Variable | Where | Purpose |
|----------|--------|--------|
| **session_id** / **session.id** | v2_sessions.id, API session/status | Identify the current homework attempt; use in all session-scoped API calls. |
| **session.status** | v2_sessions.status, API session.status (inside session) | **Single source of truth for current step**; drive UI and which APIs to call. |
| **warm_up_task** | v2_sessions snapshot + API warm_up_task | Prompt text for step 1. |
| **task_block** | From POST recording-1 or GET task-block | The 3 metric questions for step 2. |
| **final_task_text** | v2_sessions.final_task_text | Prompt for step 3 (final recording). |
| **recording_1_id** / **recording_2_id** | v2_sessions | Link to recordings table; do not use to derive step when status is present. |
| **storage_path** | Returned by recording-upload-url; stored on recordings row | Where the frontend uploads the audio blob; sent back in POST recording-1/2. |
| **performance_score_1/2/end** | v2_sessions, recordings | Scores for reporting and focus task selection. |
