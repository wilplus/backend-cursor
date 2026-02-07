# 503 – "v2_warm_up_tasks table missing or sync failed"

If you see that message or a **503** on `/warm-up-tasks`, the backend is failing because the **warm-up** tables are missing, a **column** is missing, or the request (e.g. sync) failed.

---

## PGRST204: column `max_performance_score` missing (most common)

Error: **"Could not find the 'max_performance_score' column of 'v2_warm_up_tasks' in the schema cache"** (PGRST204). Two possibilities:

1. **PostgREST cache stale (very common)** — Column already exists but PostgREST is serving an old schema. **Try this first:** run `NOTIFY pgrst, 'reload schema';` in Supabase SQL Editor, **wait 5–10 seconds**, then retry Save. No ALTER needed.
2. **Column really missing** — Table was created without it; a later migration wasn’t run. Then run the migration below.

**Type note:** We use **DECIMAL(3,2)** (0–1) to match the backend. If the column was added elsewhere as INTEGER, `ADD COLUMN IF NOT EXISTS` won’t change it; run NOTIFY anyway — the cache is often the real issue.

### Fix: run the migration (one go)

In Supabase SQL Editor (same project as backend `SUPABASE_URL`), run:

**migrations/v2_add_max_performance_score_to_tasks.sql**

Or paste this (adds column to both warm-up and focus tasks, then reloads PostgREST):

```sql
-- Warm-up tasks
ALTER TABLE public.v2_warm_up_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00
CHECK (max_performance_score >= 0 AND max_performance_score <= 1);

-- Focus tasks (in case it was created without this column)
ALTER TABLE public.v2_focus_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00
CHECK (max_performance_score >= 0 AND max_performance_score <= 1);

-- Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';
```

Backend uses **0–1** scale (1.00 = easiest). We use DECIMAL to match; do not use `INTEGER DEFAULT 10` if the app sends 0–1.

**After running the migration:** run **`NOTIFY pgrst, 'reload schema';`** (it’s in the migration), then **wait 5–10 seconds** before retrying Save. PostgREST must reload its cache.

### Verify column exists and type

Run this and paste the full output if you need to debug:

```sql
SELECT column_name, data_type, numeric_precision, numeric_scale, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'v2_warm_up_tasks'
ORDER BY ordinal_position;
```

Check that `max_performance_score` appears with the type you expect (e.g. numeric/decimal, default 1.00). If the column is already there but you still get PGRST204, **reload the cache only:**

```sql
NOTIFY pgrst, 'reload schema';
```

Then wait 5–10 seconds and try Save again.

**Focus tasks (optional):**

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'v2_focus_tasks'
ORDER BY ordinal_position;
```

If `max_performance_score` is missing there too, the migration above adds it.

### Then test

1. Admin panel → student profile → Warm-up Tasks (and Focus tasks).
2. Click **+ Add**, enter task text and max score, click **Save**.
3. Should return **200/201** instead of 503.

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
