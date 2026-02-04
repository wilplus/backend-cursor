# Backend sync: Admin panel simplified

This document keeps the backend API aligned with the **current Next.js admin panel** (two routes only: students list + student profile).

---

## Frontend shape

- **`/admin/students`** — List: email, sessions count, avg score, last active. Click row → profile.
- **`/admin/students/:id`** — Single profile with:
  - **Homework Configuration:** Warm-up tasks (per student), Focus tasks (assigned from global pool), Post-recording questions (exactly 3 from pool), Metrics (5 fixed, label-only). Buttons: Send Homework, Save.
  - **Speaker Profile:** Single “Context” textarea → stored as `coach_notes`.
  - **Reports History:** List from `sessions[].report_preview.report_text_preview` + `created_at`.

No separate Exercises / Tasks / Questions / Metrics pages; all config is from the student profile. The backend **still exposes** the same admin APIs because the profile uses them (modals for pool selection, CRUD).

---

## Contract the backend implements

### Students

- **GET /v2/admin/students** — Query: `limit`, `offset`. Response: `{ "students": [ { "user_id", "email", "user_email", "sessions_count?", "last_session_at?", "avg_performance?" } ], "limit", "offset" }`.
- **GET /v2/admin/students/:id** — Profile: `user_id`, `email`, `overrides` (at least `assigned_post_question_ids` [], `assigned_next_task_ids` [] — always arrays), `speaker_profile` (at least `coach_notes`), `warm_up_tasks`, `last_report`, `last_report_preview`, `sessions`: `[{ id, created_at, status?, report_preview?: { report_text_preview? } }]`.
- **PUT /v2/admin/students/:id/overrides** — Body: `assigned_next_task_ids`, `assigned_post_question_ids` (exactly 3 when set), optionally others. Backend enforces exactly 3 for `assigned_post_question_ids`.
- **PUT /v2/admin/students/:id/speaker-profile** — Body: `{ "coach_notes"?: string, ... }`. Frontend sends the single Context as `coach_notes`.
- **POST /v2/admin/students/:id/send-assignment** — No body. Response: `{ "status": "ok" }` or similar.

### Warm-up tasks (per student)

- **GET /v2/admin/students/:id/warm-up-tasks** — `{ "warm_up_tasks": [ { "id", "user_id", "text", "order_index?", "created_at?" } ] }`.
- **POST /v2/admin/students/:id/warm-up-tasks** — Body: `{ "text", "order_index"? }`. Response: `{ "warm_up_task": { ... } }`.
- **PUT /v2/admin/students/:id/warm-up-tasks/:task_id** — Body: `{ "text"?, "order_index"? }`. Response: `{ "warm_up_task": { ... } }`.
- **DELETE /v2/admin/students/:id/warm-up-tasks/:task_id** — Response: 200, `{ "status": "ok" }`.

### Tasks (global pool)

- **GET /v2/admin/tasks** — `{ "tasks": [ { "id", "title", "prompt_text?", "min_task_score?", "max_task_score?", "is_active?", "created_at?" } ] }`.
- **POST /v2/admin/tasks** — Body: `{ "title", "prompt_text?", ... }`. Response: `{ "task": { ... } }`.
- **PUT /v2/admin/tasks/:id** — Body: partial. Response: `{ "task": { ... } }`.
- **DELETE /v2/admin/tasks/:id** — Response: 200, `{ "status": "ok" }`.

### Post-recording questions (global pool)

- **GET /v2/admin/post-recording-questions** — `{ "questions": [ { "id", "text", "answer_type", "code?", "is_active?" } ] }`.
- **POST /v2/admin/post-recording-questions** — Body: `{ "text", "answer_type"? }`. Response: `{ "question": { ... } }`.
- **PUT /v2/admin/post-recording-questions/:id** — Body: partial. Response: `{ "question": { ... } }`.
- **DELETE /v2/admin/post-recording-questions/:id** — Response: 200, `{ "status": "ok" }`.

### Metrics (global, 5 fixed)

- **GET /v2/admin/metrics** — `{ "metrics": [ { "code", "left_label", "right_label" }, ... ] }`. Frontend expects at least one, displays up to 5.
- **PUT /v2/admin/metrics** — Body: `{ "metrics": [ { "code", "left_label", "right_label" }, ... ] }`. Response: `{ "status": "ok" }`.

---

## Behaviour

- **Auth:** All `/v2/admin/*` require valid Supabase JWT + admin check. 401 unauthenticated, 403 not admin.
- **Students list email:** Response includes `email` and `user_email` (same value) per row.
- **Reports history:** Profile `sessions` include `report_preview.report_text_preview` and `created_at`.
- **Overrides:** Backend persists `assigned_next_task_ids` and `assigned_post_question_ids`; enforces exactly 3 for questions when provided.

---

## Optional / unused by simplified UI

- **Exercises** — No Exercises page; endpoints kept for possible future use. Profile does not call them.
- **Metric questions** (position 1 & 2) — No separate admin section; still used by homework flow (student-facing). Endpoints: GET/POST/PUT/DELETE /v2/admin/metric-questions.
