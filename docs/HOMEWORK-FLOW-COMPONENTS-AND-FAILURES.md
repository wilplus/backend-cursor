# Homework flow: explanation for Cursor

This document explains the **student homework flow**, **components involved**, and **what can go wrong** so Cursor (or any developer) can reason about the system and fix issues.

---

## 1. What the flow is

The **homework flow** is a linear, 5-step speaking practice for students:

| Step | UI name        | What the student does | Backend status      |
|------|----------------|------------------------|---------------------|
| 0    | (no session)   | Clicks “Start”         | —                   |
| 1    | Warm-up        | Records warm-up; sees real-time wheel | `warm_up`           |
| 2    | Metric answers | Answers 3 self-rating questions       | `task_block`        |
| 3    | Final task     | Records final task; sees wheel again  | `final_task_ready`  |
| 4    | Post-questions | Answers reflective questions          | `post_questions`     |
| 5    | Report         | Sees final report and score           | `completed`         |

**Single source of truth:** The backend’s **`session.status`** (and only that) drives which step the user is on. The frontend must derive step from GET session/status and overwrite local state on every successful status response. No deriving step from URL, recording IDs, or cached state.

---

## 2. End-to-end flow (sequence)

1. **Load / resume**  
   Frontend calls **GET session/status**.  
   - If `has_active_session: false` or no session → clear state, show “Start”; no session-scoped calls until **POST session/start**.  
   - If active session exists → apply full status to state (sessionId, step, warmUpText, taskBlock from session_metric_question_1/2/3, finalTaskText, etc.).

2. **Step 0 → 1**  
   User clicks Start → **POST session/start**. Backend returns `session_id`, `warm_up_task` (id, text). Frontend stores sessionId and shows step 1.

3. **Step 1 (warm-up recording)**  
   - Frontend gets **recording-upload-url** (recording `"1"`) only when step === 1.  
   - User records; frontend uploads blob to **Supabase Storage** (bucket from API), then **POST recording-1** with `storage_path` + `duration_seconds`.  
   - In parallel, **recording-metrics-chunk** pipeline sends PCM chunks to BFF → backend; backend returns `pause_score` / `voiced_ratio`; frontend updates **wheel**.  
   - After recording-1 success, frontend calls **GET session/status** again and applies response (step becomes 2).

4. **Step 2 (metric answers)**  
   - Frontend shows 3 questions (from status `session_metric_question_1/2/3` or GET task-block if backend exposes it).  
   - User submits → **POST metric-answers**. Frontend then **GET session/status** and applies (step becomes 3, `final_task_text` appears).

5. **Step 3 (final task recording)**  
   - Same pattern as step 1 but for recording `"2"`: recording-upload-url (recording `"2"`), upload, **POST recording-2**, and wheel via **recording-metrics-chunk**.  
   - After recording-2 success, **GET session/status** → step 4.

6. **Step 4 (post-questions)**  
   - Frontend fetches question list via **GET questions** (status only has `post_question_ids`).  
   - User submits → **POST post-answers**. Backend generates report, sets status to `completed`, stores `post_answers` and `context_long`.  
   - Frontend **GET session/status** → step 5.

7. **Step 5 (report)**  
   - Report text from `session.context_long`; score from `session.performance_score_end`. No further API calls.

---

## 3. Components involved

| Component | Role | Repo / location |
|-----------|------|------------------|
| **Frontend** | React/Next UI: steps, recorder, wheel, forms. Calls BFF (same-origin). Derives step from GET session/status only; applies status to state; refetches status after every step-advancing mutation. | Separate frontend repo |
| **BFF** | Next.js API routes that proxy to the Flask backend. Must forward **Authorization** and correct headers/body for every homework route. Exposes e.g. `/api/homework/session/status`, `/api/homework/session/[sessionId]/recording-metrics-chunk`, etc. | Same as frontend repo (API routes) |
| **Backend (Flask)** | This repo. Serves `/v2/homework/...`: session/status, session/start, recording-upload-url, recording-1, recording-2, task-block, metric-answers, questions, post-answers, **recording-metrics-chunk**. Auth via JWT. Persists to Supabase DB. | This repo (`routes/homework.py`, `services/db.py`, etc.) |
| **Supabase DB** | PostgreSQL. Tables: `v2_sessions`, `recordings`, `v2_reports`, `v2_warm_up_tasks`, `v2_metric_questions`, `v2_student_post_recording_questions`, etc. Session holds status, snapshots (warm_up_task_text, final_task_text, session_metric_question_1/2/3), post_question_ids, post_answers (JSONB), context_long, performance_score_end. | Supabase project |
| **Supabase Storage** | Object store for audio. Bucket: **`audio_recordings`**. Path pattern: `{user_id}/{session_id}/{uuid}.webm`. RLS must allow INSERT for the authenticated user. Backend returns `storage_path` and `bucket` from recording-upload-url; frontend must use that bucket. | Supabase project |

---

## 4. What could go wrong (by area)

### 4.1 Step / status wrong (409, wrong screen, “session not found”)

| Cause | Where | Fix |
|-------|--------|-----|
| Frontend derives step from URL or recording_1_id/recording_2_id instead of `session.status` | Frontend | Derive step only from `session.status`; overwrite on every GET status. |
| Frontend caches old step and doesn’t overwrite after GET status | Frontend | On every successful GET session/status, set step (and related state) from response. |
| `has_active_session: false` but frontend keeps old sessionId and calls session-scoped APIs | Frontend | When `has_active_session === false` or no session id, clear sessionId and step; require POST start before any session call. |
| BFF doesn’t forward Authorization for status (or other routes) | BFF | Every homework BFF route must send `Authorization: Bearer <token>` to backend. |
| Backend returns 404/401 for valid session | BFF / Backend | Check BFF forwards auth; check backend auth middleware and DB session lookup. |

### 4.2 Recording upload (403, 413, “recording not found”)

| Cause | Where | Fix |
|-------|--------|-----|
| Wrong bucket (e.g. frontend uses `recordings` instead of `audio_recordings`) | Frontend | Use **bucket** from recording-upload-url response. |
| Storage RLS doesn’t allow INSERT for user | Supabase | Add RLS policy for `auth.uid()` on bucket `audio_recordings`. See `docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md`. |
| Upload URL called for recording "1" when step is already 3 | Frontend | Call recording-upload-url with `recording: "1"` only when step === 1; with `recording: "2"` only when step === 3. |
| Body over size limit | Backend / Frontend | Backend has MAX_CONTENT_LENGTH (e.g. 25MB). Keep recordings under limit. |

### 4.3 Wheel not working

| Cause | Where | Fix |
|-------|--------|-----|
| Frontend posts to localhost (e.g. 127.0.0.1:7242/ingest) instead of BFF | Frontend | Chunk pipeline must POST to **same-origin** BFF (e.g. `/api/homework/session/:id/recording-metrics-chunk`). |
| BFF route missing or wrong path | BFF | Implement POST `.../recording-metrics-chunk` proxying to backend with body + auth + X-Sample-Rate, X-Seq, X-T-Ms. |
| BFF doesn’t forward Authorization | BFF | Backend returns 401 without auth; wheel gets no data. |
| Frontend doesn’t update UI from response | Frontend | On 200, set wheel state from `response.pause_score` (and optionally `voiced_ratio`). |
| Pipeline runs on step 2 or 4 (optional strictness) | Frontend | Start chunk pipeline only on step 1 or 3 when recorder is active; stop when leaving step. |
| Backend returns 409 INVALID_SESSION_STATE | Backend / Frontend | Session status must be one of warm_up, task_block, final_task_ready, post_questions. If completed or missing, refetch status and gate pipeline. |

See **`docs/FIX-WHEEL-NOT-WORKING.md`** for full checklist.

### 4.4 Blank screens (missing task block, final task, report, questions)

| Cause | Where | Fix |
|-------|--------|-----|
| Frontend expects `task_block` or `final_task` object in status | Frontend | Backend doesn’t send those. Use `session.session_metric_question_1/2/3` for step 2; use `session.final_task_text` for final task; use `session.context_long` for report. |
| Frontend expects `report_text` | Frontend | Backend sends **`session.context_long`** for report text. |
| Step 4: frontend expects questions in status | Frontend | Status only has `post_question_ids`. Call **GET questions** when step === 4 and questions empty. |
| Step 2: no questions (taskBlock empty) | Frontend | Build task block from `session_metric_question_1/2/3` in status; or call GET task-block if backend exposes it and block still missing. |

See **`docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md`** §4 for contract realities.

### 4.5 Post-recording questions not saved

| Cause | Where | Fix |
|-------|--------|-----|
| `v2_sessions` table has no `post_answers` column | DB | Run migration `migrations/v2_sessions_add_post_answers.sql` (ADD COLUMN post_answers JSONB). |
| Frontend sends wrong body (e.g. `answer` instead of `answer_text`) | Frontend | Backend expects `{ "answers": [ { "question_id": "...", "answer_text": "..." } ] }`. |

See **`docs/FIX-POST-RECORDING-QUESTIONS-NOT-SAVED.md`**.

### 4.6 Auto-start / retry

| Cause | Where | Fix |
|-------|--------|-----|
| POST session/start fails (network, auth, backend down) and user is stuck | Frontend | Provide visible “Start / Retry” button; don’t permanently block retries with `autoStartAttempted`. |

---

## 5. Key docs (index)

| Doc | Purpose |
|-----|--------|
| **docs/taskmaster/APP-DESCRIPTION.md** | Single unified description of the app (this flow + components + contracts). |
| **docs/STEPS-TO-MAKE-FLOW-WORK.md** | Ordered implementation checklist and “Definition of Done”. |
| **docs/IMPLEMENT-THIS-TO-MAKE-FLOW-WORK.md** | Full checklist (status, refetch, thin status, BFF, wheel, bucket). |
| **docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md** | Example status payloads and §4 contract realities (no task_block/final_task/report_text; snake_case; minimal mapping). |
| **docs/FIX-WHEEL-NOT-WORKING.md** | Wheel troubleshooting (BFF, auth, same-origin, step gating, pause_score). |
| **docs/FIX-POST-RECORDING-QUESTIONS-NOT-SAVED.md** | Post-answers not persisted (migration + request shape). |
| **docs/BACKEND-FRONTEND-FLOW-FIT.md** | Backend–frontend fit and API calls per step. |
| **docs/homework-bff-routes/** | Reference BFF route implementations (status, recording-metrics-chunk, etc.). |

---

## 6. Summary for Cursor

- **Flow:** Linear 5 steps (0–5); step comes only from **GET session/status** → **session.status**; overwrite UI state on every status response.
- **Components:** Frontend (React, same-origin BFF), BFF (proxies + auth), Backend (this repo, Flask), Supabase DB + Storage.
- **Failures:** Wrong step → status-first and overwrite; 401/404 → BFF auth and routes; wheel → same-origin BFF + auth + use pause_score; blank screens → use session.* fields and GET questions/task-block when thin; post-answers not saved → add post_answers column and send correct body; upload 403 → bucket + RLS.
- **Single app description:** See **`docs/taskmaster/APP-DESCRIPTION.md`**.
