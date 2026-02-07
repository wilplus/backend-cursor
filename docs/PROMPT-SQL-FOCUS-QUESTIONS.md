# Prompt: SQL for focus questions

**Use this when you need to add the focus-questions tables to the database.** Run the migration below on your Supabase/Postgres DB (after your base v2 schema exists and `auth.users` is available).

---

## What to do

Create two tables, same pattern as warm-up tasks:

1. **v2_focus_question_pool** — global pool of focus questions (admin adds/edits/deletes).
2. **v2_focus_questions** — per-student focus questions (one row per question per student).

Run this SQL:

```sql
-- Focus questions: clone of warm-up (pool + per-student list)

CREATE TABLE IF NOT EXISTS v2_focus_question_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_focus_question_pool_order ON v2_focus_question_pool(order_index);

CREATE TABLE IF NOT EXISTS v2_focus_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  pool_question_id UUID REFERENCES v2_focus_question_pool(id) ON DELETE SET NULL,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_focus_questions_user ON v2_focus_questions(user_id);
```

---

## Checklist

- [ ] Run the SQL above on the target database.
- [ ] Ensure `auth.users` exists (v2 schema already applied).
- [ ] Backend implements admin API for these tables (see **docs/FRONTEND-PROMPT-FOCUS-QUESTIONS.md** or **docs/PROMPT-FRONTEND-FOCUS-QUESTIONS.md** for the API contract).
