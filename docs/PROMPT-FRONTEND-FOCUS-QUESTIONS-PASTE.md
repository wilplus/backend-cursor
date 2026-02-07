# Paste this in your frontend repo — Focus questions

Backend is ready. Do the following on the **frontend** so the Focus questions section works (no more 404).

---

## 1. BFF: proxy focus-questions to the backend

Ensure your Next.js (or other) BFF has routes that forward to the backend **with admin auth**:

- **GET** ` /api/admin/students/[id]/focus-questions` → backend `GET <BACKEND_URL>/v2/admin/students/<id>/focus-questions`
- **POST** ` /api/admin/students/[id]/focus-questions` → backend `POST <BACKEND_URL>/v2/admin/students/<id>/focus-questions`  
  Body: `{ "text": "...", "order_index": 0, "max_performance_score": 1 }`
- **PUT** ` /api/admin/students/[id]/focus-questions/[questionId]` → backend `PUT <BACKEND_URL>/v2/admin/students/<id>/focus-questions/<questionId>`  
  Body: `{ "text?", "order_index?", "max_performance_score?" }`
- **DELETE** ` /api/admin/students/[id]/focus-questions/[questionId]` → backend `DELETE <BACKEND_URL>/v2/admin/students/<id>/focus-questions/<questionId>`

Optional (for “Manage list” / add from pool):

- **GET** ` /api/admin/focus-question-pool` → backend `GET <BACKEND_URL>/v2/admin/focus-question-pool`  
  Response: `{ "focus_question_pool": [ { "id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }`
- **PUT** ` /api/admin/students/[id]/focus-questions` with body `{ "pool_question_ids": ["uuid", ...] }` → backend same path, to sync from pool.

Use the same auth and `BACKEND_URL` pattern as your existing admin routes (e.g. warm-up-tasks or students profile).

---

## 2. Admin UI (if not already done)

On the **student profile** page, the **Focus questions** section should:

- **On load:** Call `GET /api/admin/students/<id>/focus-questions`. Use the response `focus_questions` array (each item: `id`, `text`, `order_index`, `max_performance_score`).
- **List:** Show one row per focus question (order by `order_index`). Each row: question **text**, **Edit**, **Delete**.
- **Add focus question:** Opens modal with “Question text” (required) and “Max score (0–1)” (optional, default 1). On Save → `POST /api/admin/students/<id>/focus-questions` with `{ text, order_index: currentListLength, max_performance_score: 1 }`, then refetch the list.
- **Edit:** Modal with same fields; Save → `PUT /api/admin/students/<id>/focus-questions/<question_id>` with `{ text, max_performance_score? }`, then refetch.
- **Delete:** Confirm → `DELETE /api/admin/students/<id>/focus-questions/<question_id>` → refetch.

Same UX as **Warm-up tasks**. No limit on how many focus questions a student can have.

---

## 3. Checklist

- [ ] BFF proxies `GET/POST/PUT/DELETE` for `/api/admin/students/[id]/focus-questions` (and by `[questionId]` for PUT/DELETE) to backend `/v2/admin/students/.../focus-questions`.
- [ ] Student profile loads focus questions on open and shows list + Add / Edit / Delete.
- [ ] Optional: BFF for `/api/admin/focus-question-pool` and “Manage list” or “Add from pool” using pool + sync.
