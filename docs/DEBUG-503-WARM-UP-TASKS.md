# 503 – "v2_warm_up_tasks table missing or sync failed"

If you see that message or a **503** on `/warm-up-tasks`, the backend is failing because the **warm-up** tables are missing or the request (e.g. sync) failed.

---

## Fix: create the warm-up tables

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

**v2_schema_unified.sql** creates `v2_warm_up_tasks` without that column. The backend expects it for sync/create. Add it in Supabase SQL Editor:

```sql
ALTER TABLE v2_warm_up_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
```

---

## See the real error (like focus-tasks)

In DevTools → **Network** → click the failing **warm-up-tasks** request → **Response**.  
The JSON may include **`detail`** or **`message`** with the actual DB/backend error (e.g. relation does not exist, permission denied, column missing). Use that to fix the underlying issue.
