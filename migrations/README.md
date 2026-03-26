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

## Student UI: coach assignment video flag

- **`add_video_shown_to_student_overrides.sql`** — adds `v2_student_overrides.video_shown` (`0` | `1`, default `1`). Backend sets `0` when homework completes and `1` when admin send-assignment succeeds. `GET /v2/homework/session/status` returns `video_shown` and omits tutor video fields when `0`. See **`docs/VIDEO_SHOWN-CONTRACT.md`**.
- **`add_homework_credits_charged_at.sql`** — adds `v2_sessions.homework_credits_charged_at` (TIMESTAMPTZ). Backend deducts **5 credits when a session completes with a report** (not at `session/start`). Backfills `completed` rows so they are not charged again on deploy. **In-flight** sessions started before deploy may have been charged at start under the old logic; if one completes after deploy, credits may drop by 5 again — rare; adjust balance manually if needed.

---

## Admin / coach grade

- **`add_coach_grade_to_v2_sessions.sql`** — adds `v2_sessions.coach_grade` (SMALLINT 1–10, nullable). Lets admins grade a completed session in the admin panel. Run after v2_sessions exists.
- **`add_report_comment_to_v2_sessions.sql`** — adds `v2_sessions.report_comment` (TEXT, nullable). Optional short coach-written note shown next to the grade in the full report view.
- **`docs/migrations/session_sniper_metrics_rating.sql`** — same as above (idempotent): ensures `coach_grade` exists. Also documents that `session_sniper_metrics.session_id` must reference an existing `v2_sessions.id` so BFF/client only write after session/start. Run on Supabase (or wherever session_sniper_metrics lives).
- **`add_student_rating_session_sniper_metrics.sql`** — adds `session_sniper_metrics.student_rating_1_10` (legacy column name; SMALLINT, nullable). Current product scale is **1–5** even though the column name stays the same; only sessions with self-rating >= 4 or coach_grade >= 8 update the Sniper baseline. Run after add_user_sniper_profile.sql.
- **`add_session_sniper_completion_fields.sql`** — adds richer completion payload fields to `session_sniper_metrics` (`recording_id`, `duration_seconds`, `pitch_center_st`, `pitch_frame_count`, `frontend_level`, `frontend_step`, `completed`, `valid_for_progression`) and authoritative `realtime_level_at_session` / `realtime_step_at_session` snapshot columns to `v2_sessions`.
- **`add_realtime_progression_to_user_sniper_profile.sql`** — adds `realtime_level`, `realtime_step`, `realtime_pitch_baseline_st`, `sessions_with_pitch_count`, and `realtime_last_completed_session_id` to `user_sniper_profile`. Use this for the recorder Level/Step UI; backend increments step on completed sessions and caps at step 10 by default.
- **`add_recording_reviews.sql`** — adds `recording_reviews` (whole-session ML labels) and `recording_review_annotations` (time-span labels on a recording). Admin-only, internal training data; keep separate from `coach_grade`, report text, and student-facing feedback.
- **`add_admin_import_fields_to_recordings.sql`** — adds `recording_origin` and `source_metadata` to `recordings` so admin-imported files can carry origin/source metadata without going through homework sessions.
- **`reshape_recording_reviews_for_imports.sql`** — reshapes `recording_reviews` to support standalone imported recordings: adds `id` PK, makes `session_id` optional, preserves session-level uniqueness, and converts `overall_quality` to text for categorical labels like `good`, `bad`, `unclear`.

---

## Permissions (if you see 42501 / permission denied)

- **`grant_sniper_tables_service_role.sql`** — grants `service_role` full access to `user_sniper_profile` and `session_sniper_metrics`. Run in Supabase SQL Editor if GET /user/sniper-profile or POST .../self-rating returns 500 with "permission denied for table ...".