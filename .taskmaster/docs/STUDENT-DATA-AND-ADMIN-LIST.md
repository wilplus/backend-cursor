# Where student data lives and why new students were missing

## Where student data is stored (SQL / Supabase)

- **Identity (who is a student):** Supabase **Auth** — `auth.users`. When a student signs up (e.g. email/password or OAuth), a row is created here with `id` (UUID) and `email`. There is **no separate "students" table** in the app schema.

- **Per-student configuration (assigned by coach in admin):**
  - **`v2_warm_up_tasks`** — Warm-up tasks assigned to each student (`user_id`). Coach assigns from **`v2_warm_up_task_pool`** via admin (PUT `/admin/students/<user_id>/task-warm-up` with `pool_task_ids`). If a student has **zero** rows here, the homework flow returns **NO_WARMUP_CONFIGURED** and the student sees "No warm-up tasks are configured for your account. Please contact your coach to get started."
  - **`v2_student_overrides`** — Overrides per student (e.g. assigned_next_task_ids). One row per `user_id`.
  - **`v2_speaker_profiles`** — Coach notes, goals, etc. One row per `user_id`.
  - **`v2_student_post_recording_questions`** — Reflective questions assigned to the student (synced from pool by admin).

- **Activity:**
  - **`v2_sessions`** — One row per homework session (`user_id`, `status`, recording ids, report, etc.).

So: **students** = auth users; their **data** is spread across `auth.users` (identity) and the tables above (config + sessions). There is no single "students" table to insert into when someone registers; registration only creates the row in `auth.users`.

## Why new students did not appear in the admin panel

The admin students list was built from **user_ids that have at least one row in `v2_sessions`** (`v2_list_users_with_sessions`). A **newly registered** student has **no sessions yet**, so they never appeared in that list. The coach could not assign warm-up tasks to them because they were not visible.

## Why the student saw "No warm-up tasks configured"

Warm-up tasks are **per student** in `v2_warm_up_tasks`. They are assigned by the coach from the pool. A new student has **0** warm-up tasks until the coach assigns them. So when the student calls POST start (or GET status), the backend calls `v2_get_assigned_warm_up_task(user_id)`, gets `None`, and returns **422 NO_WARMUP_CONFIGURED** with the message shown in the screenshot.

## Fix (admin list source)

The admin students list is changed to use **all auth users** (Supabase Auth Admin API: list users), so that **newly registered** students appear immediately. The coach can then open each student, assign warm-up tasks from the pool (and optionally focus tasks, post-recording questions), and the student can run the full homework flow.

- **Before:** `user_ids` = from `v2_sessions` only → new students never in list.
- **After:** `user_ids` = from Auth Admin API list users (with optional pagination) → all registered users appear; stats (sessions_count, etc.) still come from `v2_sessions` and may be null for new students.

See `services/db.py`: `v2_list_auth_users()` and `routes/v2_routes.py`: `v2_admin_students()`.
