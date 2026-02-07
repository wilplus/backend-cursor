# 503 – "v2_warm_up_tasks table missing or sync failed"

If you see that message or a **503** on `/warm-up-tasks`, the backend is failing because the **warm-up** tables are missing, a **column** is missing, or the request (e.g. sync) failed.

---

## PGRST204: column `max_performance_score` missing (most common)

If the real error is **`PGRST204`: PostgREST can't find column `max_performance_score` on `public.v2_warm_up_tasks`**, the table exists but that column is missing (or PostgREST hasn’t reloaded its schema cache yet).

### 1) Add the column (Supabase project used by backend `SUPABASE_URL`)

Run in Supabase SQL Editor:

```sql
ALTER TABLE public.v2_warm_up_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
```

(Backend expects 0–1; use DECIMAL to match. If you prefer integer for simplicity, use `integer` and ensure the app sends 0 or 1.)

### 2) Force PostgREST to reload schema cache

Supabase/PostgREST may not see the new column immediately. Run:

```sql
NOTIFY pgrst, 'reload schema';
```

(Or: `SELECT pg_notify('pgrst', 'reload schema');`)

### 3) Verify the column exists

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'v2_warm_up_tasks'
ORDER BY ordinal_position;
```

### 4) Retry the admin Save

Warm-up task create should stop returning 503 once the column exists and PostgREST has reloaded.

If it still errors, confirm you added the column in the **same** Supabase project that backend `SUPABASE_URL` points to (not a different project/environment).

---

## Fix: create the warm-up tables (if tables are missing)

The backend expects:

- **v2_warm_up_task_pool** (global pool)
- **v2_warm_up_tasks** (per-student tasks)

**Option A – full v2 schema (recommended if you use v2)**  
Run in your Supabase SQL Editor (same project as `SUPABASE_URL`):

- **migrations/v2_schema_unified.sql**  
  (includes the warm-up tables in section 6)

**Option B – only warm-up tables**  
If you already have the rest of v2:

1. Run **migrations/v2_warm_up_task_pool.sql** (creates pool + link).
2. Ensure **v2_warm_up_tasks** exists. If it doesn’t, run the block that creates it from **v2_schema_unified.sql** (section 6), or run **v2_schema_unified.sql** once.

---

## Verify tables exist

In Supabase SQL Editor:

```sql
SELECT
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_warm_up_task_pool') AS pool_exists,
  (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_warm_up_tasks') AS tasks_exists;
```

You want **pool_exists = 1** and **tasks_exists = 1**. If either is 0, run the migrations above in the **same** Supabase project the backend uses.

---

## If the error says `column "max_performance_score" does not exist`

See **PGRST204** above: add the column, then `NOTIFY pgrst, 'reload schema';`, then verify and retry.

---

## See the real error (like focus-tasks)

In DevTools → **Network** → click the failing **warm-up-tasks** request → **Response**.  
The JSON may include **`detail`** or **`message`** with the actual DB/backend error (e.g. relation does not exist, permission denied, column missing). Use that to fix the underlying issue.
