# Frontend update prompt — copy this into your frontend repo

Use this prompt in your **frontend** repo (e.g. paste into Cursor or give to your dev) to align the UI with the current backend.

---

## What to do

### 1. Post-recording questions: 0 or any number (not “exactly 3”)

The backend **no longer** requires exactly 3 reflective questions. A student can have **0, 1, 2, 3, or any number** of post-recording questions.

**Student homework flow (step 4):**

- Call **GET /api/homework/session/<sessionId>/questions**.
- If the response has **questions: []** (or length 0), **skip** the reflective-questions step and go straight to the report (e.g. after recording 2).
- If **questions** has one or more items, render **that many** questions. Each item has `id`, `text`, `answer_type`. Collect one answer per question and send **POST /api/homework/session/<sessionId>/post-answers** with body:
  ```json
  { "answers": [ { "question_id": "<uuid>", "answer_text": "..." }, ... ] }
  ```
- The number of items in `answers` can be 1, 2, 3, or any N — match the length of `questions` from the GET response. Do **not** assume there are always 3 questions.

**Admin panel (student profile / overrides):**

- **assigned_post_question_ids** is an array of question IDs. The backend accepts **any length**: 0 (none), 1, 2, 3, or more.
- Remove any validation or UI that forces “exactly 3” (e.g. “Select exactly 3 questions”). Allow:
  - No questions selected (empty array or don’t send the field).
  - One or more questions selected (send the array of IDs in **PUT /api/admin/students/:id/overrides** with `assigned_post_question_ids`).
- Update any copy that says “exactly 3” or “3 questions” to something like “Reflective questions (optional)” or “Select 0 or more questions.”

**Admin panel: same UX as warm-up tasks for post-recording questions**

Use the **same pattern** as warm-up tasks on the student profile (add / edit / remove, no limit):

- **List UI:** Show assigned post-recording questions as a **list** (in assignment order), not chips. Each row: question text + **Edit** + **Remove**.
- **Add:** A single “Add post-recording question” (or similar) button that opens a modal where the admin can:
  - **Create new:** Enter question text and answer type → create in the pool (POST to admin post-recording-questions) and add the new question ID to this student’s `assigned_post_question_ids`, then save overrides (PUT overrides with the updated array).
  - **Or add from pool:** Show pool questions that are **not** already in `assigned_post_question_ids`; clicking one adds that ID to the draft list (user clicks Save in Homework Configuration to persist).
- **Edit:** “Edit” on a row opens a modal to change question text and answer type; save updates the pool (PUT to admin post-recording-questions/:id). Same question is shared by all students who have it assigned.
- **Remove:** “Remove” unassigns the question for this student only (remove that ID from `assigned_post_question_ids` in the draft; Save in Homework Configuration persists). Do **not** delete the question from the global pool.
- **No limit:** Allow 0 or any number of assigned questions. No “exactly 3” or “max 3” validation or copy.
- **Copy:** e.g. “Post-Recording Questions (N assigned)”, “Optional. Add, edit, or remove questions for this student. No limit.”

**Summary:** Step 4 is optional. Backend returns as many questions as are assigned; frontend shows that many and submits the same number of answers. Admin can assign 0 or any number. On the admin student profile, manage post-recording questions like warm-up tasks: list with Add (create or from pool), Edit, Remove.

---

### 2. Backend connectivity and step 2 (metric questions)

- Ensure **NEXT_PUBLIC_API_URL** points at your Flask backend (no trailing slash). If the app shows “Backend server is not responding”, fix this and CORS first.
- Ensure all homework BFF routes exist (see backend repo `docs/homework-bff-routes/`), including **GET session/[sessionId]/task-block** so step 2 can load the 3 metric questions on resume.
- **Step 2** (after first recording): Use **task_block** from the recording-1 response (or from GET task-block when resuming). Show the **3 metric questions** using **metric_question_1.text**, **metric_question_2.text**, **metric_question_3.text** as labels (not “Question 1” etc.). Submit **answer_1**, **answer_2**, **answer_3** to **POST session/:sessionId/metric-answers**, then show **final_task** for step 3.

---

### 3. Checklist

- [ ] **Step 4 (reflective questions):** If GET questions returns `questions: []`, skip the step and go to report. If it returns N questions, show N inputs and send N answers in post-answers.
- [ ] **Admin overrides:** Allow 0 or any number of post-recording questions for a student; remove “exactly 3” validation and copy.
- [ ] **Admin post-recording UX:** Same as warm-up tasks: list of assigned questions with Add (create new + add from pool), Edit (update pool), Remove (unassign). No limit on count.
- [ ] **Connectivity:** NEXT_PUBLIC_API_URL correct; BFF routes in place; step 2 uses task_block and the 3 metric question texts.

---

Copy the sections above into your frontend repo and implement the changes. If something is unclear, refer to the backend repo **docs/APP-DESCRIPTION-FRONTEND.md** for the full flow.

**Focus questions (clone of warm-up):** For a second, warm-up-style list named **focus questions** (pool + per-student add/edit/delete), use the full prompt in **docs/FRONTEND-PROMPT-FOCUS-QUESTIONS.md** — it includes the SQL migration, backend API contract, and frontend admin UI spec.
