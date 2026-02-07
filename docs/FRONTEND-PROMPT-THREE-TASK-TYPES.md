# Frontend prompt: Three task types (task_warm_up, task_focus, post_recording_questions)

**Paste this into the frontend repo** so the frontend can implement the unified admin UI for warm-up tasks, focus tasks, and post-recording questions. All three use the **same mechanism**: pool + per-student list, same API shape and UI pattern.

---

## 1. Base URL and auth

- Base: **`/v2/admin`** (or your BFF that proxies to the backend).
- All requests require **admin auth** (same as existing admin panel).

---

## 2. Three sections on student profile

On the **student profile** page (`GET /v2/admin/students/<user_id>`), the backend returns:

- **`task_warm_up`** — array of warm-up tasks assigned to this student.
- **`task_focus`** — array of focus tasks assigned to this student.
- **`post_recording_questions`** — array of post-recording questions assigned to this student.

**Do not** use `overrides.assigned_post_question_ids` for post-recording anymore. Post-recording is managed only via the per-student endpoints below. You can ignore `assigned_post_question_ids` in overrides for the reflective-questions UI.

---

## 3. Same UI pattern for all three

For **Task warm-up**, **Task focus**, and **Post-recording questions**, use the **same** UI:

1. **List** — show the items for this student (from `task_warm_up`, `task_focus`, or `post_recording_questions` in the profile).
2. **"+ Add"** — add a new item (either from pool or create inline, depending on your UX).
3. **"Manage list"** — open a modal to select items from the **pool**; on **Confirm selection**, call the **PUT sync** endpoint with the chosen pool IDs (order = display order).
4. **Edit** — edit one item (PUT by id).
5. **Delete** — delete one item (DELETE by id).

Reuse the same components for all three sections; only the labels and API paths differ.

---

## 4. API reference

### Task warm-up

**Pool (global)**

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/v2/admin/task-warm-up-pool` | — | `{ "task_warm_up_pool": [ { "id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }` |
| POST | `/v2/admin/task-warm-up-pool` | `{ "text", "order_index?", "max_performance_score?" }` | `{ "task_warm_up": { ... } }` |
| PUT | `/v2/admin/task-warm-up-pool/<pool_id>` | `{ "text?", "order_index?", "max_performance_score?" }` | `{ "task_warm_up": { ... } }` |
| DELETE | `/v2/admin/task-warm-up-pool/<pool_id>` | — | `{ "status": "ok" }` |

**Per student**

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/v2/admin/students/<user_id>/task-warm-up` | — | `{ "task_warm_up": [ { "id", "user_id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }` |
| PUT | `/v2/admin/students/<user_id>/task-warm-up` | `{ "pool_task_ids": [ "uuid", ... ] }` | `{ "task_warm_up": [ ... ] }` — sync from pool (Confirm selection) |
| POST | `/v2/admin/students/<user_id>/task-warm-up` | `{ "text", "order_index?", "max_performance_score?" }` | `{ "task_warm_up": { ... } }` |
| PUT | `/v2/admin/students/<user_id>/task-warm-up/<task_id>` | `{ "text?", "order_index?", "max_performance_score?" }` | `{ "task_warm_up": { ... } }` |
| DELETE | `/v2/admin/students/<user_id>/task-warm-up/<task_id>` | — | `{ "status": "ok" }` |

---

### Task focus

**Pool (global)**

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/v2/admin/task-focus-pool` | — | `{ "task_focus_pool": [ { "id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }` |
| POST | `/v2/admin/task-focus-pool` | `{ "text", "order_index?", "max_performance_score?" }` | `{ "task_focus": { ... } }` |
| PUT | `/v2/admin/task-focus-pool/<pool_id>` | `{ "text?", "order_index?", "max_performance_score?" }` | `{ "task_focus": { ... } }` |
| DELETE | `/v2/admin/task-focus-pool/<pool_id>` | — | `{ "status": "ok" }` |

**Per student**

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/v2/admin/students/<user_id>/task-focus` | — | `{ "task_focus": [ { "id", "user_id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }` |
| PUT | `/v2/admin/students/<user_id>/task-focus` | `{ "pool_task_ids": [ "uuid", ... ] }` | `{ "task_focus": [ ... ] }` — sync from pool (Confirm selection) |
| POST | `/v2/admin/students/<user_id>/task-focus` | `{ "text", "order_index?", "max_performance_score?" }` | `{ "task_focus": { ... } }` |
| PUT | `/v2/admin/students/<user_id>/task-focus/<task_id>` | `{ "text?", "order_index?", "max_performance_score?" }` | `{ "task_focus": { ... } }` |
| DELETE | `/v2/admin/students/<user_id>/task-focus/<task_id>` | — | `{ "status": "ok" }` |

---

### Post-recording questions

**Pool (global)**

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/v2/admin/post-recording-questions-pool` | — | `{ "post_recording_questions_pool": [ { "id", "text", "answer_type", "code?", "is_active?", "created_at" }, ... ] }` |
| POST | `/v2/admin/post-recording-questions-pool` | `{ "text", "answer_type?", "code?" }` | `{ "post_recording_question": { ... } }` |
| PUT | `/v2/admin/post-recording-questions-pool/<question_id>` | `{ "text?", "answer_type?", "code?" }` | `{ "post_recording_question": { ... } }` |
| DELETE | `/v2/admin/post-recording-questions-pool/<question_id>` | — | `{ "status": "ok" }` |

**Per student**

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/v2/admin/students/<user_id>/post-recording-questions` | — | `{ "post_recording_questions": [ { "id", "user_id", "pool_question_id?", "text", "order_index", "answer_type", "code?", "created_at" }, ... ] }` |
| PUT | `/v2/admin/students/<user_id>/post-recording-questions` | `{ "pool_question_ids": [ "uuid", ... ] }` | `{ "post_recording_questions": [ ... ] }` — sync from pool (Confirm selection) |
| POST | `/v2/admin/students/<user_id>/post-recording-questions` | `{ "text", "order_index?", "answer_type?" }` | `{ "post_recording_question": { ... } }` |
| PUT | `/v2/admin/students/<user_id>/post-recording-questions/<question_id>` | `{ "text?", "order_index?", "answer_type?", "code?" }` | `{ "post_recording_question": { ... } }` |
| DELETE | `/v2/admin/students/<user_id>/post-recording-questions/<question_id>` | — | `{ "status": "ok" }` |

---

## 5. Student profile response (GET /v2/admin/students/<user_id>)

The profile returns:

- **`task_warm_up`** — array (replaces legacy `warm_up_tasks`).
- **`task_focus`** — array (replaces legacy `focus_tasks`).
- **`post_recording_questions`** — array (replaces use of `overrides.assigned_post_question_ids` for reflective questions).
- **`overrides`** — still includes `assigned_next_task_ids`; **do not** use `assigned_post_question_ids` for the post-recording UI (use the per-student endpoints above).

---

## 6. What to remove in the frontend

- Any **old** warm-up UI that used different paths (e.g. `warm-up-task-pool`, `warm-up-tasks`) or response keys (`warm_up_task_pool`, `warm_up_tasks`). Use **task-warm-up-pool** and **task-warm-up** and keys **task_warm_up_pool** / **task_warm_up**.
- Any **old** focus UI that used **focus-task-pool** or **focus-tasks** or keys **focus_task_pool** / **focus_tasks**. Use **task-focus-pool** and **task-focus** and keys **task_focus_pool** / **task_focus**.
- Any **post-recording** UI that wrote or read **assigned_post_question_ids** in overrides (e.g. "Homework Configuration" saving post questions into overrides). Use instead **GET/PUT/POST/DELETE** `/v2/admin/students/<user_id>/post-recording-questions` and the **post-recording-questions-pool** for the pool. Display list from profile **post_recording_questions**.

Keep **exactly one** implementation per type, mirroring the same pattern for all three.

---

## 7. Summary

- **Three sections:** Task warm-up, Task focus, Post-recording questions.
- **Same UI:** list, + Add, Manage list (select from pool → Confirm selection = PUT sync), Edit, Delete.
- **Paths:** `task-warm-up-pool`, `task-warm-up` (per student); `task-focus-pool`, `task-focus` (per student); `post-recording-questions-pool`, `post-recording-questions` (per student).
- **Sync body:** `pool_task_ids` for warm-up and focus; `pool_question_ids` for post-recording.
- **Response keys:** `task_warm_up`, `task_focus`, `post_recording_questions` (and pool keys as above).
- **Homework flow:** Step 4 (reflective questions) is driven by the **per-student post_recording_questions** table; no overrides needed for that.
