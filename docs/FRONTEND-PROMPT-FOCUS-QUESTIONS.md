# Frontend prompt: Focus questions (clone of warm-up tasks)

Use this in your **frontend** repo (and give the SQL + API contract to your backend if needed) to add **focus questions** with the same behavior as warm-up tasks: pool + per-student list, add / edit / delete, no limit.

---

## 1. What are focus questions?

**Focus questions** are a second list of tasks/questions per student, implemented exactly like **warm-up tasks**:

- **Global pool:** `v2_focus_question_pool` — admin can add/edit/delete items (text, order_index, max_performance_score).
- **Per-student list:** `v2_focus_questions` — each student has their own rows; admin adds (create new or from pool), edits, and deletes on the student profile.
- **No limit** on how many focus questions a student can have (0 or any number).

Same UX as the existing “Warm-up tasks” section: list with “Add focus question”, Edit, Delete per row; optional “add from pool” in the add modal.

---

## 2. SQL migration (run on your DB)

Run this migration **after** your base v2 schema (so `auth.users` exists). Backend repo path: `migrations/v2_focus_questions.sql`.

```sql
-- ============================================================================
-- Focus questions: clone of warm-up tasks (pool + per-student list)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_focus_question_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_focus_question_pool_order ON v2_focus_question_pool(order_index);

CREATE TABLE IF NOT EXISTS v2_focus_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  pool_question_id UUID REFERENCES v2_focus_question_pool(id) ON DELETE SET NULL,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_focus_questions_user ON v2_focus_questions(user_id);
```

---

## 3. Backend API contract

The backend must expose the same HTTP API as for warm-up tasks, with names changed to **focus questions**.

### 3.1 Focus question pool (global)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v2/admin/focus-question-pool` | List all pool items. Response: `{ "focus_question_pool": [ { "id", "text", "order_index", "max_performance_score", "created_at" }, ... ] }` |
| POST | `/v2/admin/focus-question-pool` | Create pool item. Body: `{ "text": "...", "order_index": 0, "max_performance_score": 1 }`. Response: `{ "focus_question": { ... } }` |
| PUT | `/v2/admin/focus-question-pool/<pool_id>` | Update pool item. Body: `{ "text?", "order_index?", "max_performance_score?" }`. Response: `{ "focus_question": { ... } }` |
| DELETE | `/v2/admin/focus-question-pool/<pool_id>` | Delete pool item. Response: `{ "status": "ok" }` |

### 3.2 Per-student focus questions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v2/admin/students/<user_id>/focus-questions` | List this student’s focus questions (order by order_index). Response: `{ "focus_questions": [ { "id", "user_id", "text", "order_index", "pool_question_id", "max_performance_score", "created_at" }, ... ] }` |
| POST | `/v2/admin/students/<user_id>/focus-questions` | Create a new focus question for this student. Body: `{ "text": "...", "order_index": 0, "max_performance_score": 1 }`. Response: `{ "focus_question": { ... } }` |
| PUT | `/v2/admin/students/<user_id>/focus-questions/<question_id>` | Update this student’s focus question. Body: `{ "text?", "order_index?", "max_performance_score?" }`. Response: `{ "focus_question": { ... } }` |
| DELETE | `/v2/admin/students/<user_id>/focus-questions/<question_id>` | Delete this student’s focus question. Response: `{ "status": "ok" }` |
| PUT | `/v2/admin/students/<user_id>/focus-questions` (sync from pool) | Optional. Body: `{ "pool_question_ids": [ "uuid", ... ] }`. Replace student’s list with copies from the pool (same pattern as warm-up sync). Response: `{ "focus_questions": [ ... ] }` |

All admin routes must be protected (e.g. require admin token). BFF in the frontend should proxy these under `/api/admin/...` (e.g. `/api/admin/focus-question-pool`, `/api/admin/students/[id]/focus-questions`).

---

## 4. Frontend admin UI (student profile)

Add a **Focus questions** section on the **student profile** page, mirroring the existing **Warm-up tasks** section.

### 4.1 Layout and data

- **Section title:** e.g. “Focus questions”.
- **Description:** e.g. “Questions/tasks for this student. Add, edit, delete. No limit.”
- **Load:** On opening the student profile, call `GET /api/admin/students/<id>/focus-questions` and optionally `GET /api/admin/focus-question-pool` if you support “add from pool”.
- **Display:** A **list** of the student’s focus questions (ordered by `order_index`). Each row shows:
  - Question **text**
  - Optional: **Max score** (0–1) if you use it (editable inline or in edit modal)
  - **Edit** button
  - **Delete** button

### 4.2 Add

- **Button:** “Add focus question” (or “Add focus task”).
- **Modal (create new):**
  - Field: **Question text** (required).
  - Optional: **Max score** (0–1), **Order index** if you need it.
  - On Save: `POST /api/admin/students/<id>/focus-questions` with `{ text, order_index?, max_performance_score? }`. Then refresh the list.
- **Optional: “Add from pool”** in the same modal:
  - Show items from `GET /api/admin/focus-question-pool` that are not already in the student’s list (or use a “Sync from pool” flow with `PUT .../focus-questions` and `pool_question_ids`).
  - If you support “add from pool” by copying one item: create a per-student row from the pool item (backend may offer a dedicated endpoint or you use POST with the pool item’s text and metadata).

### 4.3 Edit

- **Edit** on a row opens a modal with the same fields (text, max score). On Save: `PUT /api/admin/students/<id>/focus-questions/<question_id>` with the updated fields. Then refresh the list.

### 4.4 Delete

- **Delete** on a row: confirm, then `DELETE /api/admin/students/<id>/focus-questions/<question_id>`. Then refresh the list.

### 4.5 Copy / UX parity with warm-up

- Reuse the same patterns as **Warm-up tasks**: list + “Add” button + modal for create/edit, optional “Manage list” or “Add from pool”. No limit on the number of focus questions.

---

## 5. Checklist

- [ ] **Backend:** Migration `v2_focus_questions.sql` run; tables `v2_focus_question_pool` and `v2_focus_questions` exist.
- [ ] **Backend:** Admin routes implemented for pool (GET/POST/PUT/DELETE) and per-student focus questions (GET/POST/PUT/DELETE, optional PUT sync).
- [ ] **Frontend BFF:** Proxies for `/api/admin/focus-question-pool` and `/api/admin/students/[id]/focus-questions` (and by id for PUT/DELETE).
- [ ] **Frontend admin:** Student profile has a “Focus questions” section: list, Add (create new + optional add from pool), Edit, Delete. No limit on count.

---

Copy this entire document into your frontend repo (and share the SQL + API contract with backend) to implement focus questions the same way as warm-up tasks.
