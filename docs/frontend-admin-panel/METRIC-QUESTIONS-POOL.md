# Metric questions pool (metric_question_1, 2, 3)

There are **3 metric questions** answered by the student in the homework flow. Their text is **editable in the admin panel**, with the **same mechanics as the warm-up-task-pool**: list, add, edit, delete.

- **Variable names in the student flow:** `metric_question_1`, `metric_question_2`, `metric_question_3` (and answers `answer_1`, `answer_2`, `answer_3`).
- **Backend:** The first 3 items in the pool (by `order_index`) are used as metric_question_1, 2, 3. Run **`migrations/v2_metric_questions_pool.sql`** to create the table and seed 3 default questions.

## API (backend; BFF proxies to these)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v2/admin/metric-questions-pool` | List all pool questions. Response: `{ "metric_questions_pool": [ { id, text, order_index, created_at }, ... ] }` |
| POST | `/v2/admin/metric-questions-pool` | Add a question. Body: `{ "text": "...", "order_index": 0 }`. Response: `{ "metric_question": { id, text, ... } }` |
| PUT | `/v2/admin/metric-questions-pool/<question_id>` | Update (text, order_index). |
| DELETE | `/v2/admin/metric-questions-pool/<question_id>` | Remove from pool. |

## BFF routes (same pattern as warm-up-task-pool)

- **`src/app/api/admin/metric-questions-pool/route.ts`** — GET (list), POST (add). Copy from `docs/frontend-admin-panel/api-routes/metric-questions-pool-route.ts`.
- **`src/app/api/admin/metric-questions-pool/[questionId]/route.ts`** — PUT, DELETE. Copy from `docs/frontend-admin-panel/api-routes/metric-questions-pool-[questionId]-route.ts`.

Use the same auth and `getBackendUrl()` as for warm-up-task-pool.

## Frontend prompt (admin panel: list + add/edit like warm-up-task-pool)

Implement the **Metric questions** section in the admin panel so that:

1. **List** — Call **GET /api/admin/metric-questions-pool**. Render the list from **`response.metric_questions_pool`** (array). Show each item’s **text** and **order_index**. The **first 3** by order are the ones used in the student flow as metric_question_1, metric_question_2, metric_question_3; you can show a label like “#1”, “#2”, “#3” for the first three.

2. **Add** — “Add” (or “Enter new item” + Add) calls **POST /api/admin/metric-questions-pool** with body `{ "text": "<user input>", "order_index": <next index> }`. On success, append the returned **metric_question** to the list or refetch.

3. **Edit** — Each row has an Edit action. On save, call **PUT /api/admin/metric-questions-pool/:questionId** with body `{ "text": "...", "order_index": ... }`. Refresh or update local state on success.

4. **Delete** — Delete action calls **DELETE /api/admin/metric-questions-pool/:questionId**. Refresh the list on success. (Note: if you delete one of the first 3, the student flow will use the new first 3.)

5. **Student flow** — The homework flow returns **task_block.metric_question_1**, **metric_question_2**, **metric_question_3** (each `{ id, text }`). The student submits **answer_1**, **answer_2**, **answer_3** (or **metric_answer_1**, **metric_answer_2**, **metric_answer_3**) in **POST /api/homework/session/:sessionId/metric-answers** with body `{ "answer_1": "...", "answer_2": "...", "answer_3": "..." }`.

**Summary:** Admin has a list of metric questions (same UX as warm-up-task-pool: list, add, edit, delete). The first 3 by order_index are used in the student flow as metric_question_1, metric_question_2, metric_question_3. Student sends answer_1, answer_2, answer_3 when submitting metric answers.
