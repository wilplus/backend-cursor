# Prompt: Frontend — focus questions

**Use this in your frontend repo** to add the **Focus questions** feature on the admin student profile. Same UX as **Warm-up tasks**: list with Add / Edit / Delete, no limit. Assumes the backend already has the focus-questions tables and API (see **docs/PROMPT-SQL-FOCUS-QUESTIONS.md** for SQL if needed).

---

## 1. Backend API to call (via your BFF)

Your BFF must proxy these to the backend (e.g. `/v2/admin/...` with admin auth):

**Pool (optional, for “add from pool”):**

- `GET /api/admin/focus-question-pool` → `{ focus_question_pool: [ { id, text, order_index, max_performance_score, created_at }, ... ] }`
- `POST /api/admin/focus-question-pool` — body: `{ text, order_index?, max_performance_score? }`
- `PUT /api/admin/focus-question-pool/<pool_id>` — body: `{ text?, order_index?, max_performance_score? }`
- `DELETE /api/admin/focus-question-pool/<pool_id>`

**Per-student (required):**

- `GET /api/admin/students/<user_id>/focus-questions` → `{ focus_questions: [ { id, user_id, text, order_index, pool_question_id, max_performance_score, created_at }, ... ] }`
- `POST /api/admin/students/<user_id>/focus-questions` — body: `{ text, order_index?, max_performance_score? }` → creates one focus question for this student
- `PUT /api/admin/students/<user_id>/focus-questions/<question_id>` — body: `{ text?, order_index?, max_performance_score? }`
- `DELETE /api/admin/students/<user_id>/focus-questions/<question_id>`

Optional: `PUT /api/admin/students/<user_id>/focus-questions` with body `{ pool_question_ids: [ "uuid", ... ] }` to sync student list from pool (like warm-up).

---

## 2. Admin UI on student profile

Add a **Focus questions** section (same layout as **Warm-up tasks**):

- **Title:** “Focus questions”
- **Description:** “Questions/tasks for this student. Add, edit, delete. No limit.”
- **On load:** Fetch `GET /api/admin/students/<id>/focus-questions`. Optionally fetch `GET /api/admin/focus-question-pool` if you support “add from pool”.
- **List:** Show each focus question in order (`order_index`). Each row: **text** + **Edit** + **Delete**. Optionally show **Max score** (0–1) and make it editable.
- **Add:** Button “Add focus question”. Opens modal:
  - **Create new:** fields “Question text” (required), optional “Max score” (0–1). On Save → `POST .../focus-questions` with `{ text, order_index: listLength, max_performance_score?: 1 }`, then refresh list.
  - **Add from pool (optional):** In the same modal, list items from the pool that aren’t already in the student’s list; clicking one adds it (e.g. POST with that item’s text, or use backend sync endpoint if available).
- **Edit:** “Edit” opens modal with same fields; Save → `PUT .../focus-questions/<question_id>` with updated data, then refresh.
- **Delete:** “Delete” → confirm → `DELETE .../focus-questions/<question_id>` → refresh list.

Reuse the same components/patterns as the existing Warm-up tasks section (list, modal, buttons). No limit on how many focus questions a student can have.

---

## 3. Checklist

- [ ] BFF routes: proxy `/api/admin/focus-question-pool` and `/api/admin/students/[id]/focus-questions` (and by id for PUT/DELETE) to the backend with admin auth.
- [ ] Student profile page: new “Focus questions” section with list, “Add focus question”, Edit, Delete.
- [ ] Optional: “Add from pool” in the add modal using `GET /api/admin/focus-question-pool`.
