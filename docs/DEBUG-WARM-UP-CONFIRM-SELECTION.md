# Debug: "Confirm selection" for warm-up tasks doesn't work

Use this when the admin **ticks warm-up tasks** in the "Manage list" modal and clicks **"Confirm selection"** but nothing happens (or an error appears). For you and for other LLMs helping debug.

---

## 1. What "Confirm selection" does

1. **UI:** Admin opens **Warm-up Tasks** → **Manage list** → a modal shows the **pool** of warm-up tasks. Admin **ticks** which tasks to assign to this student, then clicks **"Confirm selection"**.
2. **Frontend:** Sends **PUT** to `/api/admin/students/<student_id>/warm-up-tasks` with body:
   ```json
   { "pool_task_ids": [ "uuid1", "uuid2", ... ] }
   ```
   (Order of IDs = display order.)
3. **Backend:** Flask route **PUT /v2/admin/students/<user_id>/warm-up-tasks** → handler `v2_admin_warm_up_tasks_sync` → calls `db.v2_sync_student_warm_up_tasks_from_pool(user_id, pool_task_ids)`.
4. **DB:** Sync logic:
   - **DELETE** all existing rows in `v2_warm_up_tasks` for this `user_id`.
   - For each ID in `pool_task_ids`, **SELECT** the row from `v2_warm_up_task_pool`, then **INSERT** into `v2_warm_up_tasks` with: `user_id`, `pool_task_id`, `text`, `order_index`, **`max_performance_score`** (from the pool row).
5. **Response:** On success → **200** and `{ "warm_up_tasks": [ ... ] }`. On failure → **503** and `{ "error": "...", "detail": "<real error>", "message": "..." }`.

So "Confirm selection" is the **sync-from-pool** operation. If it returns **503**, the UI shows "v2_warm_up_tasks table missing or sync failed" and the selection is not saved.

---

## 2. What can go wrong (and what you see)

| Symptom | Likely cause | What to do |
|--------|----------------|------------|
| **503** and banner "v2_warm_up_tasks table missing or sync failed" | Backend caught an exception during sync. Most often: **missing column `max_performance_score`** on `v2_warm_up_tasks` (PostgREST **PGRST204**), or PostgREST **schema cache stale**. | See **Section 3**. |
| **503** but no/other message | Same: backend error. Read the **response body** (DevTools → Network → the PUT request to `warm-up-tasks` → **Response**). Use **`detail`** or **`message`** for the real error. | Fix the underlying issue (e.g. column, RLS, wrong DB). |
| **400** | Request body missing or invalid (e.g. no `pool_task_ids` or not an array). | Ensure frontend sends `{ "pool_task_ids": [ ... ] }`. |
| **401/403** | Auth: BFF or backend says not admin. | Check admin token and BFF → backend auth. |
| Button does nothing / no request | Frontend bug: click handler doesn’t call the API or request is blocked. | Check Network tab: is a PUT to `.../warm-up-tasks` sent when you click Confirm? |

---

## 3. Fix for 503 (missing column or stale PostgREST cache)

The sync **INSERT**s into `v2_warm_up_tasks` and always sends **`max_performance_score`**. If that column is missing in the DB (or PostgREST doesn’t see it because of cache), you get **PGRST204** → backend returns **503**.

**Step 1 – Reload PostgREST cache (try this first)**  
In Supabase SQL Editor:

```sql
NOTIFY pgrst, 'reload schema';
```

Wait **5–10 seconds**, then click **Confirm selection** again. If the column already existed and the only issue was cache, this can fix it.

**Step 2 – Add the column if it’s missing**  
If you still get 503, add the column and reload cache. Run in Supabase (same project as backend `SUPABASE_URL`):

```sql
ALTER TABLE public.v2_warm_up_tasks
ADD COLUMN IF NOT EXISTS max_performance_score DECIMAL(3,2) DEFAULT 1.00
CHECK (max_performance_score >= 0 AND max_performance_score <= 1);

NOTIFY pgrst, 'reload schema';
```

Full migration: **migrations/v2_add_max_performance_score_to_tasks.sql**. More detail: **docs/DEBUG-503-WARM-UP-TASKS.md**.

**Step 3 – Confirm the column**  
Run:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'v2_warm_up_tasks'
  AND column_name = 'max_performance_score';
```

You should get one row. Then retry **Confirm selection**.

---

## 4. Summary for other LLMs

- **User report:** "When I tick a warm-up task and click Confirm selection, it doesn’t work."
- **Flow:** Confirm selection → **PUT** `/api/admin/students/<id>/warm-up-tasks` with **`pool_task_ids`** → backend **syncs** from pool into `v2_warm_up_tasks` (DELETE + INSERT per pool item). INSERT includes **`max_performance_score`**.
- **Observed:** 503 and UI banner "v2_warm_up_tasks table missing or sync failed."
- **Root cause:** Usually **PGRST204** – column **`max_performance_score`** missing on `v2_warm_up_tasks` (or not visible to PostgREST due to schema cache).
- **Fix:** (1) Run **`NOTIFY pgrst, 'reload schema';`** and wait 5–10 s. (2) If still 503, add column (see migration above) and NOTIFY again. (3) Frontend: on 503, show **`detail`** or **`message`** from the response so the real error is visible.
