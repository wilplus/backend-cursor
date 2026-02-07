# Migrations

## SQL in place for Students tab + tasks

The schema for the **Students** tab and **focus tasks** (no separate Tasks tab) is in:

- **`v2_all_in_one.sql`** — run this for the full v2 setup. It includes:
  - **v2_tasks** — focus task pool (title, prompt_text, min/max_task_score, is_active)
  - **v2_student_overrides** — per-student config: assigned_next_task_ids, assigned_post_question_ids, assigned_warm_up_task_id, etc.
  - **v2_warm_up_tasks** — per-student warm-up tasks (text, max_performance_score)
  - **v2_sessions** — homework flow (recording_1_id, recording_2_id, context_short, performance_score_1/2, etc.)
  - **v2_post_recording_questions_pool**, **v2_metric_questions**, **v2_metric_definitions**, **v2_reports**, **v2_speaker_profiles**
  - Recording/session columns and indexes for the homework flow

Run **v2_all_in_one.sql** in the Supabase SQL Editor (after your base schema), then reload the API schema cache. No separate migrations are required for “tasks only in the Students tab.”

Optional follow-ups (if needed):

- **v2_homework_flow.sql** — extra homework columns (subset of v2_all_in_one; use if you already ran v2_flow.sql earlier).
- **v2_speaker_profiles.sql**, **v2_add_show_exercise_step.sql**, etc. — also folded into v2_all_in_one.
