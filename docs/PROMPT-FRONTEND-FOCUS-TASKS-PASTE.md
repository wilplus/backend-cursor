# Paste this in your frontend repo — Focus tasks

The feature is **focus_tasks** (not focus-questions). The backend exposes **/focus-tasks** and **/focus-task-pool**. Do the following on the **frontend** so the “Focus tasks” section works (no more 404/500).

**Important:** The backend does **not** have `/focus-questions` anymore. It has **/focus-tasks**. Your BFF and UI must call:
- `GET/POST/PUT/DELETE /api/admin/students/[id]/focus-tasks` (and `.../focus-tasks/[taskId]` for PUT/DELETE).
- Optionally `GET /api/admin/focus-task-pool` for “Manage list”.

**SQL (backend/DB):** The tables are **v2_focus_task_pool** and **v2_focus_tasks**. They are created by running **migrations/v2_focus_tasks.sql** on your database (see backend repo). If you haven’t run that migration yet, run it so create/save works; the GET already returns 200 with an empty list if the table is missing.

---

## 1. BFF: proxy focus-tasks to the backend

Ensure your BFF forwards to the backend **with admin auth**:

- **GET** `/api/admin/students/[id]/focus-tasks` → backend `GET <BACKEND_URL>/v2/admin/students/<id>/focus-tasks`  
  Response: `{ "focus_tasks": [ { "id", "user_id", "text", "order_index", "pool_task_id", "max_performance_score", "created_at" }, ... ] }`
- **POST** `/api/admin/students/[id]/focus-tasks` → backend `POST .../focus-tasks`  
  Body: `{ "text": "...", "order_index": 0, "max_performance_score": 1 }`
- **PUT** `/api/admin/students/[id]/focus-tasks/[taskId]` → backend `PUT .../focus-tasks/<taskId>`  
  Body: `{ "text?", "order_index?", "max_performance_score?" }`
- **DELETE** `/api/admin/students/[id]/focus-tasks/[taskId]` → backend `DELETE .../focus-tasks/<taskId>`

Optional (for “Manage list” / add from pool):

- **GET** `/api/admin/focus-task-pool` → backend `GET <BACKEND_URL>/v2/admin/focus-task-pool`  
  Response: `{ "focus_task_pool": [ { "id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }`
- **PUT** `/api/admin/students/[id]/focus-tasks` with body `{ "pool_task_ids": ["uuid", ...] }` → backend same path, to sync from pool.

Use the same auth and `BACKEND_URL` as your other admin routes (e.g. warm-up-tasks).

---

## 2. Admin UI

On the **student profile** page, the **Focus tasks** section should:

- **On load:** Call `GET /api/admin/students/<id>/focus-tasks`. Use the response **focus_tasks** array (each item: `id`, `text`, `order_index`, `max_performance_score`).
- **List:** One row per focus task (order by `order_index`). Each row: **text**, **Edit**, **Delete**.
- **Add focus task:** Modal with “Task text” (required) and “Max score (0–1)” (optional, default 1). On Save → `POST .../focus-tasks` with `{ text, order_index: currentListLength, max_performance_score: 1 }`, then refetch.
- **Edit:** Same modal; Save → `PUT .../focus-tasks/<task_id>` with `{ text, max_performance_score? }`, then refetch.
- **Delete:** Confirm → `DELETE .../focus-tasks/<task_id>` → refetch.

Same UX as **Warm-up tasks**. No limit on count. Treat **200 + empty `focus_tasks`** as “no focus tasks”; do **not** show an error for that.

---

## 3. Checklist

- [ ] **Stop calling `/focus-questions`.** Backend only has **/focus-tasks**. Update BFF and API client to use **/focus-tasks** and response key **focus_tasks**.
- [ ] BFF proxies GET/POST/PUT/DELETE for `/api/admin/students/[id]/focus-tasks` (and by `[taskId]` for PUT/DELETE) to backend `/v2/admin/students/.../focus-tasks`.
- [ ] Student profile loads focus tasks on open and shows list + Add / Edit / Delete.
- [ ] Optional: BFF for `/api/admin/focus-task-pool` and “Manage list” or “Add from pool”.

---

## 4. SQL (for backend/DB)

The feature uses tables **v2_focus_task_pool** and **v2_focus_tasks**. They are **already defined** in the backend repo in **migrations/v2_focus_tasks.sql**. Someone with DB access must **run that migration** on your Supabase/Postgres so the tables exist. Until then, GET returns 200 with `focus_tasks: []`; POST/PUT will return 503 with a message to run the migration.
