# Admin pool API contract (backend response shape)

When copying BFF routes from this folder, the **backend** paths must match. Use these URLs when proxying to the Flask backend:

- **Warm-up pool:** `GET/POST/PUT/DELETE /v2/admin/task-warm-up-pool` (and `.../task-warm-up-pool/<pool_id>` for PUT/DELETE).  
  **Not** `warm-up-task-pool`.
- **Per-student warm-up:** `GET/POST/PUT/DELETE /v2/admin/students/<id>/task-warm-up` (and `.../task-warm-up/<task_id>` for PUT/DELETE).  
  **Not** `warm-up-tasks`.
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
