# Backend prompt: Flow-step overrides (skip metric questions / skip post questions)

The frontend sends **`skip_metric_questions`** and **`skip_post_questions`** in **PUT `/v2/admin/students/<id>/overrides`** and expects them in **GET student profile** under `overrides`. If the backend does not store or return these fields, the admin toggles will not persist or reload.

---

## 1. Why the toggles don’t persist

- **PUT overrides** currently accepts a JSON body and calls `db.v2_upsert_student_overrides(user_id, data)`.
- `v2_upsert_student_overrides` only persists keys that are in **`_V2_OVERRIDES_COLUMNS`**. If `skip_metric_questions` and `skip_post_questions` are not in that set (and not in the `v2_student_overrides` table), they are dropped and never saved.
- **GET student profile** returns `overrides` from `db.v2_get_student_overrides(user_id)`, which is the raw row from `v2_student_overrides`. If the columns don’t exist or are never written, the frontend never sees them.

So: the backend must **store** and **return** these two booleans.

---

## 2. Required backend behavior

### 2.1 Persist the two flags

- **Migration:** Add to `v2_student_overrides`:
  - `skip_metric_questions` BOOLEAN DEFAULT false
  - `skip_post_questions` BOOLEAN DEFAULT false
- **`services/db.py`:** Add `"skip_metric_questions"` and `"skip_post_questions"` to **`_V2_OVERRIDES_COLUMNS`** so PUT overrides accepts and persists them.
- **PUT `/v2/admin/students/<user_id>/overrides`:** No change to the route; it already passes `request.get_json()` to `v2_upsert_student_overrides`. Once the columns and allow-list are in place, the two keys will be stored.

### 2.2 Return them in GET student profile

- **GET student profile** builds `overrides` from `db.v2_get_student_overrides(user_id)`, which does `select("*")` on `v2_student_overrides`. Once the columns exist, they will be in the row. Ensure the frontend contract (e.g. `overrides.skip_metric_questions`, `overrides.skip_post_questions`) is satisfied; use `false` or omit if never set so the frontend gets a consistent shape.

---

## 3. Optional: actually skipping steps

If you want the toggles to **change the flow** (not only persist):

- **When `skip_metric_questions` is true:**  
  After recording 1, instead of setting status to `task_block` (step 2: metric questions), set status to **`final_task_ready`** (step 3) and set a default or minimal `final_task_text` so the student goes straight to recording 2. You may need to set `metric_answers` to a default (e.g. empty or placeholder) so downstream logic does not expect user input.

- **When `skip_post_questions` is true:**  
  After recording 2, instead of setting status to `post_questions` (step 4), set status to **`completed`** and generate the report (same logic as POST post-answers: compute `performance_score_end`, build report text, write to `context_long`, create `v2_reports` row, update coaching memory, send lesson-complete email if applicable). You may need to call that logic from the recording-2 handler when the override is set, or factor it into a shared “complete session” function.

Implementing this is optional; at minimum the backend must **persist and return** the two booleans so the toggles don’t disappear.

---

## 4. Checklist (implementation status)

- [x] Migration adds `skip_metric_questions` and `skip_post_questions` (BOOLEAN, default false) to `v2_student_overrides`. See **`migrations/add_skip_metric_and_post_questions_overrides.sql`**.
- [x] `_V2_OVERRIDES_COLUMNS` includes `skip_metric_questions` and `skip_post_questions`.
- [x] PUT overrides persists them; GET student profile returns them in `overrides`.
- [x] Recording-1 handler: when `skip_metric_questions` is true, after storing recording 1 the session is set to `final_task_ready` with a default `final_task_text` and empty `metric_answers`; response returns `status: "final_task_ready"` and `final_task` so the frontend can show step 3 (recording 2) immediately.
- [x] Recording-2 handler: when `skip_post_questions` is true, after storing recording 2 the completion flow runs (report generation, `completed`, coaching memory, email) and the response is the same as POST post-answers (report, scores, etc.).

### 4.1 Auto-skip when nothing to show (no crash)

Same idea as “no post-questions → straight to report”:

- **No focus tasks → skip step 2 and step 3 (straight to report):** If the student has **no focus tasks** (`v2_get_focus_tasks(user_id)` empty), after recording 1 the session goes to **`completing_from_recording_1`**. The API returns `status: "report_generating"`; the recording-1 job then generates the report from that single recording and marks the session **completed** (no metric questions, no recording 2). Frontend can show "Your report is being generated" and poll GET session/status until `status: "completed"`.
- **Coach set skip_metric_questions:** Only step 2 is skipped; student still does recording 2 (session goes to `final_task_ready` with default final task).
- **Step 4:** If the student has **no post-recording questions**, step 4 is skipped after recording 2: session is completed and report generated (same as when `skip_post_questions` is true).

So: coach overrides **or** “nothing configured” both result in skipping the step.

**Run the migration** in Supabase SQL Editor, then the flow-skips work as above.
