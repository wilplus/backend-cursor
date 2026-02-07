# Select Warm-up Tasks modal — pool + per-student assignment

The admin panel has a **"Select Warm-up Tasks"** modal where you should see **all** warm-up tasks in a pool, tick which ones apply to the current student, and confirm to save.

## Backend model

- **Global pool:** `v2_warm_up_task_pool` — one list of warm-up tasks (text, order_index, max_performance_score). No `user_id`; same pool for everyone.
- **Per student:** `v2_warm_up_tasks` — for each student, a subset of tasks **assigned from the pool** (copied so each row has `user_id`, `pool_task_id`, text, order_index, max_performance_score).

When you **Confirm Selection** in the modal, the backend **replaces** that student’s warm-up tasks with the selected pool items (in the order you chose).

## API (backend; your BFF proxies to these)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v2/admin/warm-up-task-pool` | List all pool tasks (for the modal list). Response: `{ "warm_up_task_pool": [ { id, text, order_index, max_performance_score, created_at }, ... ] }` |
| POST | `/v2/admin/warm-up-task-pool` | Add a pool task. Body: `{ "text": "...", "order_index": 0, "max_performance_score": 1 }`. Response: `{ "warm_up_task": { id, text, ... } }` |
| PUT | `/v2/admin/warm-up-task-pool/<pool_id>` | Update a pool task (text, order_index, max_performance_score). |
| DELETE | `/v2/admin/warm-up-task-pool/<pool_id>` | Remove a task from the pool. |
| GET | `/v2/admin/students/<user_id>/warm-up-tasks` | This student’s assigned warm-up tasks. Each row has `pool_task_id` when assigned from pool. Use these `pool_task_id` values to pre-tick the modal. Response: `{ "warm_up_tasks": [ { id, user_id, text, order_index, max_performance_score, pool_task_id, ... }, ... ] }` |
| PUT | `/v2/admin/students/<user_id>/warm-up-tasks` | **Sync from pool.** Body: `{ "pool_task_ids": [ "uuid1", "uuid2", ... ] }` (pool task IDs in the order you want). Replaces this student’s warm-up tasks with those pool items. Response: `{ "warm_up_tasks": [ ... ] }` |

## BFF routes to add (frontend)

1. **Pool**
   - `GET /api/admin/warm-up-task-pool` → proxy to `GET {backend}/v2/admin/warm-up-task-pool`
   - `POST /api/admin/warm-up-task-pool` → proxy to `POST {backend}/v2/admin/warm-up-task-pool`
   - `PUT /api/admin/warm-up-task-pool/[poolId]/route.ts` → proxy PUT to backend
   - `DELETE /api/admin/warm-up-task-pool/[poolId]/route.ts` → proxy DELETE to backend

2. **Student sync**
   - Same `PUT /api/admin/students/[id]/warm-up-tasks` that you use for sync must send body `{ "pool_task_ids": [...] }` to the backend (not a single-task update). So your existing BFF route for `PUT .../warm-up-tasks` should forward the JSON body as-is; the backend treats PUT with `pool_task_ids` as sync.

## Frontend prompt: implement the Select Warm-up Tasks modal

Use this prompt in your frontend app (or give it to your frontend developer) so the modal shows the pool and saves the selection per student.

---

**Prompt for frontend**

Implement the **"Select Warm-up Tasks"** modal so that:

1. **Pool is visible**
   - When the modal opens, call **GET /api/admin/warm-up-task-pool** (or your BFF equivalent) to load **all** warm-up tasks.
   - Render them in the modal as a list (e.g. with checkboxes). Show each item’s `text`; optionally show `max_performance_score` (0–1). If the pool is empty, show a message like “No items in pool yet” and rely on “Add” to create the first ones.

2. **Pre-select this student’s current assignment**
   - When opening the modal for a given student, call **GET /api/admin/students/:studentId/warm-up-tasks** to get that student’s current warm-up tasks.
   - For each returned task, use `pool_task_id` if present (or match by `text` if your backend doesn’t yet return `pool_task_id`). Pre-check the checkboxes for those pool items so the user sees which tasks are currently assigned to this student.

3. **Search (optional)**
   - If you have a “Search…” field, filter the displayed pool items by `text` (client-side or server-side) so the user can find tasks quickly.

4. **Add new item to the pool**
   - “Enter new item…” + “Add” should call **POST /api/admin/warm-up-task-pool** with body `{ "text": "new task text", "order_index": 0, "max_performance_score": 1 }`.
   - After a successful add, either append the new task to the list and auto-check it for this student, or refetch the pool and keep the current selection state. Then the user can confirm to save.

5. **Confirm selection**
   - When the user clicks **“Confirm Selection (N)”**:
     - Build an array of pool task IDs in the order you want (e.g. the order of checked items, or a dedicated order).
     - Call **PUT /api/admin/students/:studentId/warm-up-tasks** with body `{ "pool_task_ids": [ "id1", "id2", ... ] }`.
     - On success, close the modal and refresh the student’s warm-up task list on the profile (e.g. refetch GET students/:id/warm-up-tasks) so the summary shows the updated assignment.

6. **Cancel**
   - “Cancel” closes the modal without calling the sync API.

**Summary:** The modal should (a) load and show **all** warm-up tasks from the pool, (b) pre-tick the ones currently assigned to the student, (c) allow adding new pool items and ticking/unticking, and (d) on Confirm, send `pool_task_ids` in order to PUT students/:id/warm-up-tasks so the backend can replace the student’s warm-up tasks with the selected pool items.

---

## Migration note

If your database was created before the pool existed, run the migration that adds `v2_warm_up_task_pool` and the `pool_task_id` column on `v2_warm_up_tasks`:

- **New installs:** use `migrations/v2_all_in_one.sql` (it includes the pool).
- **Existing DBs:** run `migrations/v2_warm_up_task_pool.sql`.

After that, you can add pool items via the modal “Add” or via API; existing per-student warm-up tasks remain until you use “Confirm Selection” for that student (then they are replaced by the selected pool items).
