# Frontend sync prompt — align with backend

Use this prompt when building or updating the frontend so it stays in sync with the **current backend** (Flask v2 API). Copy or adapt it for your frontend repo or for an AI assistant.

---

## Instructions for the frontend

Synchronize the frontend with this backend. The backend is a **Flask API** under the base path **`/v2`** for the new flow. All v2 endpoints require **auth**: send `Authorization: Bearer <supabase_access_token>`.

- **Student app:** Call the backend at `BACKEND_URL/v2/...` (or via your own BFF that proxies to that URL with the user’s token).
- **Admin panel:** Call `BACKEND_URL/v2/admin/...` with the **admin user’s** token. The backend checks admin via the `admin_users` table; return 403 if the backend returns 403.

Implement **only** what the backend currently provides. Do **not** assume a “homework flow” with two recordings or endpoints like “get warm-up task” or “submit recording_1” — those are not implemented yet. The **current student flow** is: one v2 session → universal questions → optional exercise → pre-questions + task → **one** recording → post-answers → report.

---

## Base URL and auth

- **Base:** `https://<your-backend-host>/v2` (e.g. Railway URL).
- **Auth:** Every request (student and admin): `Authorization: Bearer <supabase_access_token>`.
- **Admin:** Same header; backend returns 403 if the user is not in `admin_users`.

---

## Student flow (current) — endpoints and contract

Implement this sequence. All under `GET/POST .../v2/...` with auth.

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

## Admin panel — endpoints and BFF mapping

All under `GET/POST/PUT/DELETE .../v2/admin/...` with admin auth. The backend returns JSON; admin panel can proxy via Next.js (or similar) BFF routes that forward the token.

### Students
- `GET /v2/admin/students` — Query: `limit`, `offset`. Response: `{ "students": [ { "user_id" } ], "limit", "offset" }`.
- `GET /v2/admin/students/<user_id>` — Response: `{ "user_id", "email", "overrides", "speaker_profile", "sessions": [ { "id", "created_at", "status", "recording_id", "report_id", "task_score", "recording_preview", "report_preview" } ] }`.
- `PUT /v2/admin/students/<user_id>/overrides` — Body: `{ "show_exercise_step"?, "assigned_post_question_ids"?, "assigned_next_exercise_id"?, "assigned_next_task_ids"?, "intended_emotion_prompt"?, "keywords_prompt"?, "emotion_check_question_text"?, ... }`. `assigned_post_question_ids` must be exactly 3 IDs if provided.
- `PUT /v2/admin/students/<user_id>/speaker-profile` — Body: speaker profile fields (e.g. `main_goal`, `motivation`, `strong_points`, `weak_points`, `charismatic_traits`, `hobbies_interests`, `personality_type`, `coach_notes`).
- `POST /v2/admin/students/<user_id>/send-assignment` — No body. Sends “new homework” email to the student (requires student email in Supabase Auth).

### Warm-up tasks (per student; for future homework flow UI)
- `GET /v2/admin/students/<user_id>/warm-up-tasks` → `{ "warm_up_tasks": [ { "id", "user_id", "text", "order_index", "created_at" } ] }`.
- `POST /v2/admin/students/<user_id>/warm-up-tasks` — Body: `{ "text", "order_index"?(default 0) }`.
- `PUT /v2/admin/students/<user_id>/warm-up-tasks/<task_id>` — Body: `{ "text"?, "order_index"? }`.
- `DELETE /v2/admin/students/<user_id>/warm-up-tasks/<task_id>` — No body; 204 or 200.

### Exercises
- `GET /v2/admin/exercises` → `{ "exercises": [ { "id", "title", "video_url", "description", "min_task_score", "max_task_score", "is_active", "created_at" } ] }`.
- `POST /v2/admin/exercises` — Body: same fields.
- `PUT /v2/admin/exercises/<exercise_id>` — Body: partial.
- `DELETE /v2/admin/exercises/<exercise_id>` — Soft delete.

### Tasks
- `GET /v2/admin/tasks` → `{ "tasks": [ { "id", "title", "prompt_text", "min_task_score", "max_task_score", "is_active", "created_at" } ] }`.
- `POST /v2/admin/tasks`, `PUT /v2/admin/tasks/<task_id>`, `DELETE /v2/admin/tasks/<task_id>` — Same pattern.

### Post-recording questions
- `GET /v2/admin/post-recording-questions` → `{ "questions": [ { "id", "code", "text", "answer_type", "is_active" } ] }`.
- `POST /v2/admin/post-recording-questions`, `PUT /v2/admin/post-recording-questions/<question_id>`, `DELETE /v2/admin/post-recording-questions/<question_id>`.

### Metric questions (two questions for future homework flow)
- `GET /v2/admin/metric-questions` → `{ "questions": [ { "id", "position": 1|2, "text", "created_at" } ] }`.
- `POST /v2/admin/metric-questions` — Body: `{ "position": 1|2, "text" }`.
- `PUT /v2/admin/metric-questions/<question_id>`, `DELETE /v2/admin/metric-questions/<question_id>`.

### Metric definitions (labels for the 5 metrics)
- `GET /v2/admin/metric-definitions` → `{ "metric_definitions": [ { "code", "left_label", "right_label" } ] }`.
- `PUT /v2/admin/metric-definitions` — Body: `{ "metric_definitions": [ { "code", "left_label", "right_label" } ] }`.
- `GET /v2/admin/metrics` — Alias: same as metric-definitions but response key `"metrics"` (for frontend that expects `metrics`).
- `PUT /v2/admin/metrics` — Body: `{ "metrics": [ ... ] }`; backend accepts and writes metric definitions.

---

## Frontend deliverables reference (admin panel)

In this repo, under **`docs/frontend-admin-panel/`**, you have:

- **README.md** — Design tokens (Tailwind), file mapping, BFF instructions, dependencies, backend endpoints list.
- **api-routes/README.md** — Exact mapping of which Next.js API route file to create for each admin endpoint (e.g. `src/app/api/v2/admin/students/route.ts`).
- **api-routes/*.ts** — Example BFF handlers that proxy to the Flask backend with the admin token.
- **lib/api/admin-client.ts** — Types (`StudentProfile`, `Exercise`, `Task`, `PostQuestion`, `WarmUpTask`, `MetricQuestion`) and `adminApi` methods matching the admin endpoints above. Add `getMetricDefinitions` / `putMetricDefinitions` (or `getMetrics` / `putMetrics`) if you use the metrics admin page.
- **app/admin/** — Example pages: layout, students list, student profile (with overrides, speaker profile, warm-up tasks, send assignment), exercises, questions, metrics.
- **components/admin/** — AdminShell (nav), SectionCard.

Copy or adapt these into your frontend app so the admin panel matches the backend. Ensure every admin action uses the correct HTTP method and path and sends the backend token; handle 401/403 and show errors when the backend returns an error body (`code`, `error`).

---

## What not to implement yet (no backend support)

- **Homework flow student steps:** “Get warm-up task”, “Submit recording_1”, “Get AI task with metric_question_1/2”, “Submit metric answers”, “Submit recording_2”, “Get/save report with performance_score_end”. These are designed but not implemented; the DB has columns (`performance_score_1`, `performance_score_2`, `performance_score_end`, `recording_1_id`, `recording_2_id`, `context_short`, `context_long`, `metric_answers`) for future use.
- **Report overwrite / context_long edit:** Admin editing of report text or `context_long` in session/history is not exposed by the backend yet.
- **Tasks by ID for student:** Student gets tasks from the plan (command_options) and optional `select-task`; there is no “get task by id” student endpoint beyond that. Admin uses `GET /v2/admin/tasks` for the pool.

---

## Summary

- **Student:** One flow only — session start → universal questions → (optional exercise) → pre-questions + task + intent → one recording upload → post-answers → report. Use the v2 endpoints and response shapes above.
- **Admin:** Use the v2 admin endpoints for students, overrides, speaker profile, send-assignment, exercises, tasks, post-recording questions, warm-up tasks, metric questions, and metric definitions. Proxy with the admin token and handle errors.
- **Sync:** Keep types (e.g. `StudentProfile`, session `status` values, overrides keys) aligned with the backend; add BFF routes for any admin endpoint you use; do not rely on homework-flow student APIs or report overwrite until the backend implements them.
