# V2 Admin API — for building the admin panel

The **backend** exposes these admin endpoints. An **admin panel** (Next.js UI) that mirrors the student flow and lets admins manage exercises and student profile is **not** built in this repo; the frontend must call these APIs.

---

## Auth

- All `/v2/admin/*` require **admin**: `Authorization: Bearer <token>` and the token’s email must be in `admin_users` with `is_active = true`. Otherwise 403.

---

## Students (users)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v2/admin/students` | List students with email. Query: `limit`, `offset`. Response: `{ students: [{ user_id, email?, sessions_count?, last_session_at?, avg_performance? }], limit, offset }`. |
| GET | `/v2/admin/students/<user_id>` | Student profile for admin panel. Response: `{ user_id, email, overrides, speaker_profile, sessions }`. `sessions` include `recording_preview` (performance_score_v2, transcription_preview) and `report_preview` (report_text_preview) when available. |
| PUT | `/v2/admin/students/<user_id>/overrides` | Set per-student overrides. Body: `intended_emotion_prompt`, `keywords_prompt`, `emotion_check_question_text`, `assigned_post_question_ids` (UUID[], must be exactly 3 if provided), `assigned_next_exercise_id` (UUID), `assigned_next_task_ids` (UUID[]). |
| PUT | `/v2/admin/students/<user_id>/speaker-profile` | Update speaker profile. Body: `main_goal`, `motivation`, `strong_points`, `weak_points`, `charismatic_traits`, `hobbies_interests`, `personality_type`, `coach_notes`. |
| POST | `/v2/admin/students/<user_id>/send-assignment` | Sends "you have new homework" email to the student (Resend). 400 if student has no email in auth; 500 if send fails. |

**Student profile ↔ flow**

- **Overrides** control what the student sees in the flow:
  - `assigned_next_exercise_id`: if set, that exercise is chosen in the “exercise” step (if it matches task_score band).
  - `assigned_post_question_ids`: if set (length 3), those 3 post-recording questions are used for that student.
  - `intended_emotion_prompt` / `keywords_prompt` / `emotion_check_question_text`: custom prompt text for that student.
- The admin panel can show the same “steps” as the student (universal questions → exercise → pre-questions → record → post-questions) and for each student show/edit these overrides so they mirror the flow.

---

## Exercises (add / update / delete)

Exercises are the ones shown in the **exercise** step after the 3 universal questions (selected by task_score; admin can force one per student via `assigned_next_exercise_id`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/v2/admin/exercises` | List all exercises (including inactive). Response: `{ exercises: [{ id, title, video_url, description, min_task_score, max_task_score, is_active, created_at }, ...] }`. |
| POST | `/v2/admin/exercises` | Create. Body: `title` (required), `video_url`, `description`, `min_task_score` (default 0), `max_task_score` (default 1), `is_active` (default true). |
| PUT | `/v2/admin/exercises/<exercise_id>` | Update same fields. |
| DELETE | `/v2/admin/exercises/<exercise_id>` | Soft-delete: sets `is_active = false` so it no longer appears in the student flow. |

Only exercises with `is_active = true` are considered in the student flow. To “restore”, PUT with `is_active: true`.

---

## Other admin (tasks, post-questions, metrics)

- **Tasks:** GET/POST/PUT/DELETE `/v2/admin/tasks` and `/v2/admin/tasks/<id>`. DELETE soft-deactivates (`is_active = false`).
- **Post-recording questions pool:** GET/POST/PUT/DELETE `/v2/admin/post-recording-questions` and `/v2/admin/post-recording-questions/<id>`.
- **Metric definitions (labels):** GET/PUT `/v2/admin/metric-definitions`. Alias for frontend spec: GET/PUT `/v2/admin/metrics` (response key `metrics`, PUT body `{ metrics: [ { code, left_label, right_label } ] }`).

---

## Building the admin panel (frontend)

1. **Students list:** Call `GET /v2/admin/students`, then for each student you can link to a profile page.
2. **Student profile:** Call `GET /v2/admin/students/<user_id>`. Show overrides and sessions. Provide forms to PUT overrides (e.g. “Next exercise” dropdown of exercises, “Post questions” multi-select, custom prompt texts).
3. **Exercises management:** A page that lists `GET /v2/admin/exercises`, with “Add exercise” (POST), “Edit” (PUT), “Delete” (DELETE). Fields: title, video_url, description, min_task_score, max_task_score, is_active.
4. **BFF:** Add Next.js API routes under e.g. `/api/v2/admin/*` that proxy to the Flask backend with the admin’s token.

The backend does **not** include any HTML or React components; the admin panel UI lives in your frontend repo and uses these endpoints.
