# Schema columns for minimal migration diff

Exact column names as in the codebase (`supabase-schema-willab-complete.sql` and idempotent `DO $$` blocks). Use this to align migrations and API field names.

---

## v2_sessions

**Base table (CREATE):**

| Column    | Type      | Notes |
|-----------|-----------|--------|
| id        | UUID      | PK, DEFAULT uuid_generate_v4() |
| user_id   | UUID      | NOT NULL, REFERENCES auth.users(id) ON DELETE CASCADE |
| status    | TEXT      | NOT NULL DEFAULT 'warm_up' |
| created_at| TIMESTAMP | DEFAULT NOW() |

**Columns added by idempotent migrations (ADD COLUMN IF NOT EXISTS):**

| Column                   | Type    | Notes |
|--------------------------|---------|--------|
| context_short             | TEXT    | |
| context_long             | TEXT    | |
| context_long_entries     | JSONB   | DEFAULT '[]' |
| selected_task_id         | UUID    | REFERENCES v2_tasks(id) ON DELETE SET NULL |
| recording_1_id           | UUID    | REFERENCES recordings(id) ON DELETE SET NULL |
| recording_2_id           | UUID    | REFERENCES recordings(id) ON DELETE SET NULL |
| performance_score_1      | FLOAT   | |
| performance_score_2      | FLOAT   | |
| performance_score_end    | FLOAT   | |
| session_metric_question_1 | TEXT    | |
| session_metric_question_2 | TEXT    | |
| session_metric_question_3 | TEXT    | |
| metric_answers           | JSONB   | |
| question_1_analysis       | TEXT    | |
| question_1_score          | FLOAT   | |
| question_2_analysis       | TEXT    | |
| question_2_score          | FLOAT   | |
| question_3_analysis       | TEXT    | |
| question_3_score          | FLOAT   | |
| pitch_variance_avg        | FLOAT   | |
| report_id                 | UUID    | FK v2_reports added separately |
| post_question_ids         | UUID[]  | |
| warm_up_task_id           | UUID    | REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL |
| warm_up_task_text         | TEXT    | |
| final_task_text           | TEXT    | |

---

## recordings

**Base table (CREATE) — existing columns:**

| Column            | Type      | Notes |
|-------------------|-----------|--------|
| id                | UUID      | PK, DEFAULT uuid_generate_v4() |
| user_id           | UUID      | REFERENCES auth.users(id) ON DELETE CASCADE |
| session_id        | UUID      | (v1 recording_sessions) |
| audio_url         | TEXT      | NOT NULL |
| duration          | INT       | NOT NULL |
| created_at        | TIMESTAMP | DEFAULT NOW() |
| transcription_text| TEXT      | |
| duration_seconds  | NUMERIC   | |
| words_per_minute  | NUMERIC   | |
| filler_words_count| JSONB     | |
| classification    | TEXT      | |
| confidence        | TEXT      | |
| storage_path      | TEXT      | |
| coaching_report   | TEXT      | |
| trend_sentence    | TEXT      | |
| command_option_id | TEXT      | |
| biofeedback_summary | JSONB   | |
| voice_stability   | NUMERIC   | |
| energy_score      | NUMERIC   | |
| pacing_score      | NUMERIC   | |

**V2 columns (ADD COLUMN if not exists):**

| Column                    | Type    | Notes |
|---------------------------|---------|--------|
| session_v2_id             | UUID    | REFERENCES v2_sessions(id) ON DELETE SET NULL |
| task_id                   | UUID    | REFERENCES v2_tasks(id) ON DELETE SET NULL |
| performance_score_v2      | FLOAT   | |
| performance_metrics_v2    | JSONB   | |
| metric_labels_snapshot_v2 | JSONB   | |

---

Use this list to generate a **minimal diff** migration: only add columns that are missing in your target DB, and keep names exactly as above for alignment with the codebase.
