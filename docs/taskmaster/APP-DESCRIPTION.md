# Unified app description (taskmaster)

Single source of truth for **what the app is**, **how the homework flow works**, and **key contracts**. Use this file when you need one place to describe the system (e.g. for Cursor, onboarding, or task planning).

---

## 1. What the app is

- **Product:** Student homework flow for speaking practice. A student goes through a fixed sequence: warm-up recording → 3 self-rating questions → final task recording → reflective questions → final report with score.
- **Users:** Students (authenticated via Supabase Auth). Admin/coach features exist in separate flows.
- **This repo:** **Backend** (Flask) and **documentation**. It does **not** contain the frontend or BFF; those live in a separate app (typically Next.js).
- **Deployment:** Backend runs as a service (e.g. Heroku, Fly, or behind a proxy). Frontend/BFF call it via a configurable base URL. Audio files are stored in **Supabase Storage**; all other data in **Supabase (PostgreSQL)**.

---

## 2. Homework flow (steps)

One active **session** per student. Session has a **status** that drives the only allowed actions and UI step.

| Step | Name           | Student action              | Backend status     | Main APIs |
|------|----------------|-----------------------------|--------------------|-----------|
| 0    | No session     | Clicks “Start”              | —                  | GET status, POST start |
| 1    | Warm-up        | Records warm-up; sees wheel | `warm_up`          | GET status, recording-upload-url (rec "1"), Storage upload, POST recording-1, POST recording-metrics-chunk (wheel) |
| 2    | Metric answers | Answers 3 questions         | `task_block`       | GET status, GET task-block (optional), POST metric-answers |
| 3    | Final task     | Records final task; wheel   | `final_task_ready` | GET status, recording-upload-url (rec "2"), upload, POST recording-2, POST recording-metrics-chunk |
| 4    | Post-questions | Answers reflective Qs       | `post_questions`   | GET status, GET questions, POST post-answers |
| 5    | Report         | Views report and score      | `completed`        | GET status (report from session.context_long, score from performance_score_end) |

- **Source of truth for “current step”:** **GET session/status** → **`session.status`**. The frontend must derive the step only from this and overwrite local state on every successful status response. No overriding from URL, recording IDs, or cache.
- **After every step-advancing action** (recording-1, metric-answers, recording-2, post-answers), the frontend calls **GET session/status** again and applies the response so the UI advances without refresh.

---

## 3. Components

| Component        | Responsibility |
|------------------|----------------|
| **Frontend**     | React/Next UI: steps, recorder, wheel, forms. Calls **same-origin BFF** only. Holds sessionId, step, warmUpText, taskBlock, finalTaskText, questions, reportText, performanceScoreEnd. Maps backend snake_case to camelCase in one place (e.g. applyStatusToState). |
| **BFF**          | Next.js API routes that proxy to the Flask backend. **Must forward Authorization** and correct headers/body for every homework route (status, start, recording-upload-url, recording-1, recording-2, recording-metrics-chunk, task-block, metric-answers, questions, post-answers). |
| **Backend**      | This repo. Flask under `/v2/homework/`. Auth via JWT. Reads/writes Supabase DB; returns storage_path and bucket for uploads. Implements session lifecycle, scoring, report generation, real-time metrics (recording-metrics-chunk). |
| **Supabase DB**  | PostgreSQL. Main tables: v2_sessions (status, snapshots, post_answers, context_long, etc.), recordings, v2_reports, v2_warm_up_tasks, v2_metric_questions, v2_student_post_recording_questions. |
| **Supabase Storage** | Bucket **audio_recordings**. Path: `{user_id}/{session_id}/{uuid}.webm`. RLS must allow INSERT for the authenticated user. |

---

## 4. Key contracts

- **Session identity:** `session_id` (top-level) and `session.id` (nested) in GET status; same value. Frontend: `sessionId = res.session_id ?? res.session?.id ?? null`. No session-scoped calls without valid sessionId.
- **Status → step:** `warm_up`→1, `task_block`→2, `final_task_ready`→3, `post_questions`→4, `completed`→5. Only from `session.status`.
- **Warm-up text:** `warm_up_task.text` or `session.warm_up_task_text`.
- **Step 2 questions:** Backend does **not** send a shaped `task_block` in status. Use `session.session_metric_question_1`, `session_metric_question_2`, `session_metric_question_3` (strings); or GET task-block if backend exposes it and block is still missing.
- **Final task text:** `session.final_task_text` only (no `final_task` object).
- **Report text:** `session.context_long` (not `report_text`).
- **Performance score (end):** `session.performance_score_end`.
- **Step 4 questions:** Status has only `post_question_ids`. Frontend must **GET questions** when step === 4 and questions empty.
- **Snake_case:** Backend uses snake_case everywhere. Frontend either reads snake_case or normalizes once (e.g. in applyStatusToState) and uses camelCase internally.
- **Recording upload:** Use **bucket** and **storage_path** from recording-upload-url response. Call recording-upload-url for recording "1" only on step 1, for "2" only on step 3.
- **Wheel:** Chunk pipeline POSTs to **same-origin** BFF `.../recording-metrics-chunk` (never localhost in production). BFF forwards auth and body. Frontend updates wheel from response **pause_score** (0–1).

---

## 5. Where to implement what

- **Backend (this repo):** Implemented. No ongoing code changes required for the flow; only migrations or fixes (e.g. add post_answers column if missing).
- **Frontend + BFF (other repo):** All flow logic: status-first step, applyStatusToState/deriveStepFromStatus, refetch after mutations, recording URL guards, wheel pipeline and BFF route, bucket from API, thin-status fill (GET questions / task-block when needed). See **docs/STEPS-TO-MAKE-FLOW-WORK.md** and **docs/IMPLEMENT-THIS-TO-MAKE-FLOW-WORK.md**.

---

## 6. Pointers to detailed docs

| Topic | Doc |
|-------|-----|
| Flow explanation, components, what can go wrong | **docs/HOMEWORK-FLOW-COMPONENTS-AND-FAILURES.md** |
| Implementation steps and Definition of Done | **docs/STEPS-TO-MAKE-FLOW-WORK.md** |
| Full implementation checklist | **docs/IMPLEMENT-THIS-TO-MAKE-FLOW-WORK.md** |
| Status response shape and contract realities | **docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md** §4 |
| Wheel not working | **docs/FIX-WHEEL-NOT-WORKING.md** |
| Post-recording questions not saved | **docs/FIX-POST-RECORDING-QUESTIONS-NOT-SAVED.md** |
| Backend–frontend fit | **docs/BACKEND-FRONTEND-FLOW-FIT.md** |
| BFF reference routes | **docs/homework-bff-routes/** |
| Storage RLS | **docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md** |
| Canonical product/backend contract | **docs/CONTRACT-HOMEWORK-FLOW.md** |

This file (**docs/taskmaster/APP-DESCRIPTION.md**) is the single unified app description. All other docs specialize or extend it.
