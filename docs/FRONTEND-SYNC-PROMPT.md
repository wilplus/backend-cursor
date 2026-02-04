# Frontend sync prompt — align with backend

Use this prompt when building or updating the frontend so it stays in sync with the **current backend** (Flask v2 API). Copy or adapt it for your frontend repo or for an AI assistant.

---

## Instructions for the frontend

Synchronize the frontend with this backend. The backend is a **Flask API** under the base path **`/v2`** for the new flow. All v2 endpoints require **auth**: send `Authorization: Bearer <supabase_access_token>`.

- **Student app:** Call the backend at `BACKEND_URL/v2/...` (or via your own BFF that proxies to that URL with the user’s token).
- **Admin panel:** Call `BACKEND_URL/v2/admin/...` with the **admin user’s** token. The backend checks admin via the `admin_users` table; return 403 if the backend returns 403.

The backend supports **two** student flows:

1. **Homework flow (recommended / replacement):** First screen = warm-up task text + record button; then recording_1 → task block + metric answers → recording_2 → questions → report. Use **`/v2/homework/...`** endpoints below.
2. **Classic v2 flow (legacy):** Universal questions → optional exercise → pre-questions + task → **one** recording → post-answers → report. Use **`/v2/session/...`** and **`/v2/recordings/upload`**.

---

## Base URL and auth

- **Base:** `https://<your-backend-host>/v2` (e.g. Railway URL).
- **Auth:** Every request (student and admin): `Authorization: Bearer <supabase_access_token>`.
- **Admin:** Same header; backend returns 403 if the user is not in `admin_users`.

---

## Student flow: Homework flow (warm_up + two recordings) — endpoints and contract

Use this flow when the first screen should be **warm-up task text + record button** only (no universal questions). All under **`/v2/homework/...`** with auth.

1. **Start**
   - `POST /v2/homework/session/start`
   - Body: `{}`
   - Response: `{ "session_id", "status": "warm_up", "warm_up_task": { "id", "text" } }` (200 or 201). If no warm-up assigned, `warm_up_task` may be null.

2. **Get warm-up task (optional; already in start)**
   - `GET /v2/homework/session/<session_id>/warm-up-task` → `{ "warm_up_task": { "id", "text" } }`.

3. **Submit recording_1**
   - `POST /v2/homework/session/<session_id>/recording-1` (multipart: `audio` file; optional `duration_seconds`).
   - Response: `{ "recording_id", "performance_score_1", "context_short", "task_block": { "context_short", "focus_task": { "id", "title", "prompt_text" }, "metric_question_1", "metric_question_2" } }`. Session moves to `task_block`.

4. **Submit metric answers**
   - `POST /v2/homework/session/<session_id>/metric-answers`
   - Body: `{ "answer_1": string, "answer_2": string }` (or `metric_answer_1`, `metric_answer_2`).
   - Response: `{ "final_task": string }`. Session moves to `final_task_ready`.

5. **Submit recording_2**
   - `POST /v2/homework/session/<session_id>/recording-2` (multipart: `audio`).
   - Response: `{ "recording_id", "performance_score_2" }`. Session moves to `post_questions`.

6. **Get questions**
   - `GET /v2/homework/session/<session_id>/questions` → `{ "questions": [ { "id", "text", "answer_type" } ] }`. If empty, skip step 7.

7. **Submit post-answers**
   - `POST /v2/homework/session/<session_id>/post-answers`
   - Body: `{ "answers": [ { "question_id", "answer_text" } ] }`. If no questions, may send `[]`.
   - Response: `{ "report_text", "performance_score_end", "performance_metrics" }`. Session moves to `completed`.

8. **Status**
   - `GET /v2/homework/session/status` → `{ "session": {...} | null, "session_id"?, "has_active_session" }`.

Homework session statuses: `warm_up` → `task_block` → `final_task_ready` → `post_questions` → `completed`.

---

## Student flow: Classic v2 (legacy) — endpoints and contract

Implement this sequence only if not using the homework flow. All under `GET/POST .../v2/...` with auth.

1. **Session start**
   - `POST /v2/session/start`
   - Body (JSON): `{}` or `{ "session_id": "<uuid>" }` to resume.
   - Response: `{ "session": { ... }, "session_id": "<uuid>" }` (200 or 201). Session has `status`, e.g. `universal_questions`, `exercise`, `pre_questions`, `recording_ready`, `post_questions`, `completed`.

2. **Universal questions**
   - `GET /v2/universal-questions` → list of questions (array).
   - After user answers: `POST /v2/session/<session_id>/universal-answers`
   - Body: `{ "mood": 0|1 or 0..1, "readiness": 1..10, "mode_preference": 0|1 }` (0 = guide me, 1 = I'll choose).
   - Response **A** (exercise step): `{ "task_score": number, "exercise": { "id", "title", "video_url", "description" }, "status": "exercise" }` → show exercise UI, then call exercise-feedback.
   - Response **B** (no exercise): `{ "session_id": "<v1_session_id>", "task_score": number, "pre_questions": [...], "command_options": [...], "recommended_command_option_id": "A"|"B"|"C", "mode", "structure", "theme_*", "biofeedback_profile", ... }` → go to pre-questions and task selection.

3. **Exercise feedback (only if step 2 returned status "exercise")**
   - `POST /v2/session/<session_id>/exercise-feedback`
   - Body: `{ "exercise_liked": true|false }`
   - Response: same shape as 2B (v1 plan with pre_questions, command_options, etc.).

4. **Task selection (if mode “I'll choose”)**
   - User may pick a task; then `POST /v2/session/<session_id>/select-task`
   - Body: `{ "task_id": "<uuid>" }`.
   - Response: `{ "task": { "id", "title", "prompt_text" } }`.

5. **Intent (emotion + keywords)**
   - `POST /v2/session/<session_id>/intent`
   - Body: `{ "intended_emotion": string, "keywords": [string, string, string] }` (exactly 3 keywords).
   - Response: `{ "status": "ok" }`.

6. **Recording upload**
   - `POST /v2/recordings/upload` (multipart/form-data)
   - Fields: `session_id`, `task_id`, `audio` (file). Optional: `duration_seconds`.
   - Response: `{ "recording_id", "performance_score", "performance_metrics", "metric_labels_snapshot" }`. Session moves to `post_questions`.

7. **Post-answers**
   - `POST /v2/session/<session_id>/post-answers`
   - Body: `{ "answers": [ { "question_id": "<uuid>", "answer_text": string } ] }`.
   - Response: `{ "report_text", "performance_score", "performance_metrics", "metric_labels_snapshot" }`. Session moves to `completed`.

8. **Session status**
   - `GET /v2/session/status` → `{ "session": {...} | null, "session_id"?, "has_active_session": boolean }`.

Error responses: `{ "code": "SESSION_NOT_FOUND"|"INVALID_STATE"|"V2_ERROR"|... , "error": string }` with appropriate 4xx/5xx status.

---

## Admin panel — simplified (two routes only)

Admin UI: **`/admin/students`** (list) and **`/admin/students/:id`** (profile). All config from the profile; no separate Exercises/Tasks/Questions/Metrics pages. Backend still exposes the same APIs (profile uses them in modals). **Full contract:** `docs/ADMIN-PANEL-SYNC.md`.

All under `GET/POST/PUT/DELETE .../v2/admin/...` with admin auth.

### Students
- `GET /v2/admin/students` — Query: `limit`, `offset`. Response: `{ "students": [ { "user_id", "email", "user_email", "sessions_count?", "last_session_at?", "avg_performance?" } ], "limit", "offset" }`.
- `GET /v2/admin/students/<user_id>` — **Profile (simplified admin: one page).** Response: `user_id`, `email`, `overrides` (always arrays for `assigned_post_question_ids`, `assigned_next_task_ids`), `speaker_profile` (at least `coach_notes`), `warm_up_tasks`, `last_report`, `last_report_preview`, `sessions` (each: `id`, `created_at`, `status`, `report_preview.report_text_preview`).
- `PUT /v2/admin/students/<user_id>/overrides` — Body: `assigned_next_task_ids`, `assigned_post_question_ids` (exactly 3 when set), optionally `assigned_warm_up_task_id`, etc.
- `PUT /v2/admin/students/<user_id>/speaker-profile` — Body: `{ "coach_notes"?: string, ... }`. Frontend sends the single “Context” as `coach_notes`.
- `POST /v2/admin/students/<user_id>/send-assignment` — No body. Response: `{ "status": "ok" }`.

### Warm-up tasks (per student; for future homework flow UI)
- `GET /v2/admin/students/<user_id>/warm-up-tasks` → `{ "warm_up_tasks": [ { "id", "user_id", "text", "order_index", "created_at" } ] }`.
- `POST /v2/admin/students/<user_id>/warm-up-tasks` — Body: `{ "text", "order_index"?(default 0) }`.
- `PUT /v2/admin/students/<user_id>/warm-up-tasks/<task_id>` — Body: `{ "text"?, "order_index"? }`.
- `DELETE /v2/admin/students/<user_id>/warm-up-tasks/<task_id>` — No body; 204 or 200.

### Exercises (unused by simplified admin; endpoints kept)
- `GET/POST/PUT/DELETE /v2/admin/exercises` — Profile does not call these.

### Tasks (global pool)
- `GET /v2/admin/tasks` → `{ "tasks": [ { "id", "title", "prompt_text", "min_task_score", "max_task_score", "is_active", "created_at" } ] }`.
- `POST /v2/admin/tasks`, `PUT /v2/admin/tasks/<task_id>`, `DELETE /v2/admin/tasks/<task_id>` — Same pattern.

### Post-recording questions
- `GET /v2/admin/post-recording-questions` → `{ "questions": [ { "id", "code", "text", "answer_type", "is_active" } ] }`.
- `POST /v2/admin/post-recording-questions`, `PUT /v2/admin/post-recording-questions/<question_id>`, `DELETE /v2/admin/post-recording-questions/<question_id>`.

### Metrics (global, 5 fixed labels)
- `GET /v2/admin/metrics` → `{ "metrics": [ { "code", "left_label", "right_label" }, ... ] }`.
- `PUT /v2/admin/metrics` — Body: `{ "metrics": [ ... ] }`.
- Metric questions (position 1 & 2): `GET/POST/PUT/DELETE /v2/admin/metric-questions` — used by homework flow; simplified profile does not edit them.

---

## Frontend deliverables reference (admin panel)

In this repo, under **`docs/frontend-admin-panel/`**, you have:

- **README.md** — Design tokens (Tailwind), file mapping, BFF instructions, dependencies, backend endpoints list.
- **api-routes/README.md** — Exact mapping of which Next.js API route file to create for each admin endpoint (e.g. `src/app/api/admin/students/route.ts`).
- **api-routes/*.ts** — Example BFF handlers that proxy to the Flask backend with the admin token.
- **lib/api/admin-client.ts** — Types (`StudentProfile`, `Exercise`, `Task`, `PostQuestion`, `WarmUpTask`, `MetricQuestion`) and `adminApi` methods matching the admin endpoints above. Add `getMetricDefinitions` / `putMetricDefinitions` (or `getMetrics` / `putMetrics`) if you use the metrics admin page.
- **app/admin/** — Example pages: layout, students list, student profile (with overrides, speaker profile, warm-up tasks, send assignment), exercises, questions, metrics.
- **components/admin/** — AdminShell (nav), SectionCard.

Copy or adapt these into your frontend app so the admin panel matches the backend. Ensure every admin action uses the correct HTTP method and path and sends the backend token; handle 401/403 and show errors when the backend returns an error body (`code`, `error`).

---

## What is not yet in the backend

- **Report overwrite / context_long edit:** Admin editing of report text or appending to `context_long_entries` in session/history is not yet exposed (report is appended server-side; admin overwrite API TBD).
- **Tasks by ID for student (classic flow):** Student gets tasks from the plan (command_options) and optional `select-task`; there is no “get task by id” student endpoint beyond that. Admin uses `GET /v2/admin/tasks` for the pool.

---

## Admin panel mockup alignment (single student profile page)

The backend is aligned with the admin panel mockup: one student profile page with **Homework Configuration**, **Speaker Profile**, and **Last Report**.

| Mockup section | Backend |
|----------------|--------|
| **Header** (email) | `GET /v2/admin/students/:id` → `email` |
| **Homework Configuration** | |
| → Send Homework | `POST /v2/admin/students/:id/send-assignment` |
| → Save | `PUT /v2/admin/students/:id/overrides` (assigned_warm_up_task_id, assigned_next_task_ids, assigned_post_question_ids, etc.) |
| → List of warm-up tasks (add, delete, edit) | Profile includes `warm_up_tasks`. CRUD: `GET/POST/PUT/DELETE /v2/admin/students/:id/warm-up-tasks` |
| → List of focus tasks (add, delete, edit) | Overrides `assigned_next_task_ids`. Pool: `GET /v2/admin/tasks`. Save via `PUT .../overrides` |
| → List of questions (add, delete, edit) | Overrides `assigned_post_question_ids` (exactly 3). Pool: `GET /v2/admin/post-recording-questions`. Save via `PUT .../overrides` |
| → Metric question 1 & 2 (editable) | `GET/POST/PUT/DELETE /v2/admin/metric-questions` |
| → Metric 3, 4, 5 (editable) | `GET/PUT /v2/admin/metrics` or `GET/PUT /v2/admin/metric-definitions` (labels for the 5 metrics) |
| **Speaker Profile** → Save | `PUT /v2/admin/students/:id/speaker-profile` (main_goal, motivation, coach_notes, etc.) |
| **Last Report** | Profile includes `last_report` (full text) and `last_report_preview` (500 chars). From latest session’s report or context_long. |

Nothing else is required in the admin panel beyond this page and the listed endpoints.

---

## Summary

- **Student:** Prefer the **homework flow** (`/v2/homework/...`): first screen = warm-up task + record; then recording_1 → task block + metric answers → recording_2 → questions → report. Alternatively, the classic flow (`/v2/session/...`, one recording) remains available.
- **Admin:** Use the v2 admin endpoints for students, overrides, speaker profile, send-assignment, exercises, tasks, post-recording questions, warm-up tasks, metric questions, and metric definitions. Proxy with the admin token and handle errors.
- **Sync:** Keep types (e.g. `StudentProfile`, session `status` values, overrides keys) aligned with the backend; add BFF routes for any admin endpoint you use; do not rely on homework-flow student APIs or report overwrite until the backend implements them.
