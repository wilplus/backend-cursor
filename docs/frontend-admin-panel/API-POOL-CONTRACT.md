# Admin pool API contract (backend response shape)

When copying BFF routes from this folder, the **backend** paths must match. Use these URLs when proxying to the Flask backend:

- **Tasks pool (global):** `GET/POST/PUT/DELETE /v2/admin/tasks-pool` (and `.../tasks-pool/<pool_id>` for PUT/DELETE).  
List / single-row responses use the JSON key `**tasks_pool`** (plural — aligns with DB table `public.tasks_pool`). Do **not** use `task_pool`.
- **Per-student tasks:** `GET/POST/PUT/DELETE /v2/admin/students/<id>/tasks` (and `.../tasks/<task_id>` for PUT/DELETE).  
Lists use `**tasks`**; create/update return `**task**`.
- **Atomic pool row + assign:** `POST /v2/admin/students/<id>/tasks/create-pool-and-assign`  
Body: JSON with required `text`; optional `order_index`, `max_performance_score`, `insert_at`.  
  - `insert_at`: omit or `"end"` to append after existing pool-linked tasks; or an integer `0..n` to insert before that index in the current pool-id order.  
  - Response **201:** `tasks_pool` (the new pool row), `tasks` (array), `dropped_non_pool_tasks` (number).  
  - `dropped_non_pool_tasks`: count of prior student rows **without** `pool_task_id` removed by sync (same as a full PUT sync from pool ids).
- **Focus pool / focus tasks:** removed from the product; legacy routes may return empty lists or **410**.

---

## Pool POST response shape (create item)


| Endpoint                    | Response status | Response body key | Example                                                                                          |
| --------------------------- | --------------- | ----------------- | ------------------------------------------------------------------------------------------------ |
| `POST /v2/admin/tasks-pool` | 201             | `tasks_pool`      | `{ "tasks_pool": { "id": "...", "text": "...", "order_index": 0, "max_performance_score": 1 } }` |


On error (e.g. table missing), backend may return 500/503 with `{ "error": "...", "detail": "...", "hint": "..." }`.