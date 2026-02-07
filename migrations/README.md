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