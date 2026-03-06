# Migrations

## Single migration for current homework flow (recommended)

- **`v2_schema_unified.sql`** — **one file** for the full v2 homework schema. Run this in the Supabase SQL Editor (after `auth.users` and `recordings` exist).
  - **Drops:** `v2_metric_questions_pool`, `v2_post_recording_questions_pool` (unused).
  - **Creates:** `v2_metric_questions` (3 positions), `v2_post_recording_questions`, `v2_tasks`, `v2_exercises`, `v2_metric_definitions`, `v2_warm_up_task_pool`, `v2_warm_up_tasks`, `v2_student_overrides`, `v2_sessions`, `v2_reports`, `v2_speaker_profiles`; adds v2 columns to `recordings`.
  - **Removes** `metric_question_1/2/3` from `v2_student_overrides` if present.
  - Idempotent: safe on existing DBs (adds missing columns only). Data in dropped pool tables is lost.

---

## Legacy / optional

- **`v2_all_in_one.sql`** — older full v2 setup (includes pool tables; prefer **v2_schema_unified.sql** for new or clean setup).
- **`v2_flow.sql`**, **v2_homework_flow.sql** — earlier stepwise migrations; superseded by **v2_schema_unified.sql** for the current flow.

---

## Coaching redesign (run after v2 schema)

- **`add_v2_student_coaching_memory.sql`** — table for last_5_scores, recent_focus_task_ids. Run before deploying backend that calls `v2_upsert_student_coaching_memory`.
- **`add_recording_1_performance_profile.sql`** — adds `v2_sessions.recording_1_performance_profile` (JSONB). **Run in Supabase first, then deploy backend**; otherwise recording_1 job fails when writing the column. Idempotent; existing sessions stay NULL.
- **`add_recording_1_processing_error_code.sql`** — adds `v2_sessions.recording_1_processing_error_code` (TEXT). When the recording-1 job fails, this stores a stable code (e.g. `transcription_failed`, `storage_error`) for logs and GET session/status. Optional; job still sets `recording_1_processing_status: "failed"` if the column is missing.
- **`add_recurring_issues_to_coaching_memory.sql`** — adds `v2_student_coaching_memory.recurring_issues` (JSONB). Run after the two above. Backend derives it from last 5 sessions’ performance profiles (e.g. too_fast if pace_level in ≥3 of 5).
- **`add_focus_task_targets_and_difficulty.sql`** — adds `v2_focus_tasks.targets` (JSONB) and `difficulty` (FLOAT). For multi-factor scoring: tasks with `targets` (e.g. `["pacing"]`) get preferred when `recurring_issues` matches (e.g. too_fast → pacing).

---

## Admin / coach grade

- **`add_coach_grade_to_v2_sessions.sql`** — adds `v2_sessions.coach_grade` (SMALLINT 1–10, nullable). Lets admins grade a completed session in the admin panel. Run after v2_sessions exists.
- **`docs/migrations/session_sniper_metrics_rating.sql`** — same as above (idempotent): ensures `coach_grade` exists. Also documents that `session_sniper_metrics.session_id` must reference an existing `v2_sessions.id` so BFF/client only write after session/start. Run on Supabase (or wherever session_sniper_metrics lives).
- **`add_student_rating_session_sniper_metrics.sql`** — adds `session_sniper_metrics.student_rating_1_10` (SMALLINT 1–10, nullable). Student self-rating; only sessions with student_rating_1_10 >= 8 or coach_grade >= 8 update the Sniper baseline. Run after add_user_sniper_profile.sql.

---

## Permissions (if you see 42501 / permission denied)

- **`grant_sniper_tables_service_role.sql`** — grants `service_role` full access to `user_sniper_profile` and `session_sniper_metrics`. Run in Supabase SQL Editor if GET /user/sniper-profile or POST .../self-rating returns 500 with "permission denied for table ...".