# Admin pool API contract (backend response shape)

When copying BFF routes from this folder, the **backend** paths must match. Use these URLs when proxying to the Flask backend:

- **Warm-up pool:** `GET/POST/PUT/DELETE /v2/admin/task-warm-up-pool` (and `.../task-warm-up-pool/<pool_id>` for PUT/DELETE).  
  **Not** `warm-up-task-pool`.
- **Per-student warm-up:** `GET/POST/PUT/DELETE /v2/admin/students/<id>/task-warm-up` (and `.../task-warm-up/<task_id>` for PUT/DELETE).  
  **Not** `warm-up-tasks`.
- **Per-student warm-up (atomic pool + assign):** `POST /v2/admin/students/<id>/task-warm-up/create-pool-and-assign`  
  Body: JSON with required `text`; optional `order_index`, `max_performance_score`, `insert_at`.  
  - `insert_at`: omit or `"end"` to append after existing pool-linked tasks; or an integer `0..n` to insert before that index in the current pool-id order.  
  - Response **201:** `task_warm_up_pool`, `task_warm_up` (array), `dropped_non_pool_tasks` (number).  
  - `dropped_non_pool_tasks`: count of prior student rows **without** `pool_task_id` removed by sync (same as a full PUT sync from pool ids).
- **Per-student focus (atomic pool + assign):** `POST /v2/admin/students/<id>/task-focus/create-pool-and-assign` — same body and semantics; returns `task_focus_pool`, `task_focus`, `dropped_non_pool_tasks`.
- **Focus pool:** `GET/POST/PUT/DELETE /v2/admin/task-focus-pool` (and `.../task-focus-pool/<pool_id>` for PUT/DELETE).

---

## Pool POST response shape (create item)

Frontend should read the created item from the key the backend returns:

| Endpoint | Response status | Response body key | Example |
|----------|-----------------|-------------------|---------|
| `POST /v2/admin/task-focus-pool` | 201 | `task_focus` | `{ "task_focus": { "id": "...", "text": "...", "order_index": 0, "max_performance_score": 1 } }` |
| `POST /v2/admin/task-warm-up-pool` | 201 | `task_warm_up` | `{ "task_warm_up": { "id": "...", "text": "...", "order_index": 0, "max_performance_score": 1 } }` |

- **Focus pool create:** use `res.task_focus` (single object).
- **Warm-up pool create:** use `res.task_warm_up` (single object).

On error (e.g. table missing), backend may return 503 with `{ "error": "...", "detail": "..." }`.
