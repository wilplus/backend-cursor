# Minimal diff migration plan (per environment)

Based on **docs/SCHEMA-COLUMNS-FOR-MIGRATION-DIFF.md**. Run these only when the target environment is missing the columns. All statements are idempotent (IF NOT EXISTS / DO $$).

---

## Prerequisites

- `v2_sessions` table exists (base: `id`, `user_id`, `status`, `created_at`).
- `recordings` table exists (base columns as in SCHEMA-COLUMNS-FOR-MIGRATION-DIFF.md).
- `v2_tasks`, `v2_warm_up_tasks`, `v2_reports` exist (for FKs).

---

## Environment checklist

Before running, confirm what you already have:

| Asset | How to check |
|-------|----------------|
| v2_sessions columns | `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions';` |
| recordings V2 columns | Same for `table_name = 'recordings'` |

---

## 1) v2_sessions — add missing columns only

Run each block only if the column is missing. Order does not matter for these; FKs reference tables that must already exist.

```sql
-- v2_sessions: homework flow and resume snapshots (idempotent)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_short') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_short TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_long TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long_entries') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_long_entries JSONB DEFAULT '[]';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'selected_task_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN selected_task_id UUID REFERENCES v2_tasks(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'recording_1_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN recording_1_id UUID REFERENCES recordings(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'recording_2_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN recording_2_id UUID REFERENCES recordings(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_1') THEN
    ALTER TABLE v2_sessions ADD COLUMN performance_score_1 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_2') THEN
    ALTER TABLE v2_sessions ADD COLUMN performance_score_2 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_end') THEN
    ALTER TABLE v2_sessions ADD COLUMN performance_score_end FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_1') THEN
    ALTER TABLE v2_sessions ADD COLUMN session_metric_question_1 TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_2') THEN
    ALTER TABLE v2_sessions ADD COLUMN session_metric_question_2 TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_3') THEN
    ALTER TABLE v2_sessions ADD COLUMN session_metric_question_3 TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'metric_answers') THEN
    ALTER TABLE v2_sessions ADD COLUMN metric_answers JSONB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_1_analysis') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_1_analysis TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_1_score') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_1_score FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_2_analysis') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_2_analysis TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_2_score') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_2_score FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_3_analysis') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_3_analysis TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_3_score') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_3_score FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'pitch_variance_avg') THEN
    ALTER TABLE v2_sessions ADD COLUMN pitch_variance_avg FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'report_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN report_id UUID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'post_question_ids') THEN
    ALTER TABLE v2_sessions ADD COLUMN post_question_ids UUID[];
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'warm_up_task_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'warm_up_task_text') THEN
    ALTER TABLE v2_sessions ADD COLUMN warm_up_task_text TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'final_task_text') THEN
    ALTER TABLE v2_sessions ADD COLUMN final_task_text TEXT;
  END IF;
END $$;
```

Then add report_id FK if missing:

```sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND constraint_name = 'v2_sessions_report_id_fkey') THEN
    ALTER TABLE v2_sessions ADD CONSTRAINT v2_sessions_report_id_fkey FOREIGN KEY (report_id) REFERENCES v2_reports(id) ON DELETE SET NULL;
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
```

---

## 2) recordings — add V2 columns only

```sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'session_v2_id') THEN
    ALTER TABLE recordings ADD COLUMN session_v2_id UUID REFERENCES v2_sessions(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'task_id') THEN
    ALTER TABLE recordings ADD COLUMN task_id UUID REFERENCES v2_tasks(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'performance_score_v2') THEN
    ALTER TABLE recordings ADD COLUMN performance_score_v2 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'performance_metrics_v2') THEN
    ALTER TABLE recordings ADD COLUMN performance_metrics_v2 JSONB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'metric_labels_snapshot_v2') THEN
    ALTER TABLE recordings ADD COLUMN metric_labels_snapshot_v2 JSONB;
  END IF;
END $$;
```

---

## Per-environment summary

| Environment | Action |
|-------------|--------|
| **Fresh / new DB** | Run full schema (e.g. `supabase-schema-willab-complete.sql`) then no extra steps if it already includes the DO $$ blocks. |
| **Existing with base v2_sessions only** | Run **§1** (v2_sessions) and **§2** (recordings). |
| **Existing with some columns** | Run **§1** and **§2** anyway; IF NOT EXISTS makes it safe — only missing columns are added. |
| **Already at parity with willab-complete** | No migration needed. |

---

## Rollback (optional)

We do not recommend dropping columns that may hold data. If you must roll back a single column (e.g. before it’s used in production), drop only that column; document which env and which column.

---

Field names match **SCHEMA-COLUMNS-FOR-MIGRATION-DIFF.md** and the codebase; no renames.
