# Debug: “Second task” not being processed

“Second task” usually means one of:

1. **Focus task (step 2)** — the task + 3 metric questions after the warm-up recording. User should see a focus task and three questions.
2. **Final task (step 3)** — the AI-generated prompt for the second recording. User should see this text before recording again.
3. **Recording_2** — the second recording upload; “not processed” can mean upload fails, or session never moves to post_questions.

Below: most likely causes and how to fix them.

---

## 1) Focus task (step 2) is null or missing

The homework flow uses the **`v2_tasks`** table for the focus task, **not** `v2_focus_tasks`. Selection is done in `select_focus_task_for_performance_score_1` using `v2_get_active_tasks()` (which reads from `v2_tasks`).

- If **`v2_tasks` has no rows**, or **no row with `is_active = true`**, then no focus task is selected → `focus_task` is **null** in:
  - **POST /session/<id>/recording-1** response (`task_block.focus_task`)
  - **GET /session/<id>/task-block** response (`task_block.focus_task`)

So the “second task” (focus task) is not processed or shown because there is nothing to select.

**Check:**

```sql
select id, title, prompt_text, min_task_score, is_active
from public.v2_tasks
where is_active = true
order by min_task_score asc;
```

If this returns **0 rows**, that’s the cause.

**Fix:**

- Add at least one active task to **`v2_tasks`** (with `min_task_score`, e.g. `0` or `0.5`, and `is_active = true`). The admin panel may expose “Tasks” (v2_tasks) separately from “Focus tasks” (v2_focus_tasks); use the one that writes to **v2_tasks** for the student flow.
- If you want the flow to use **per-student** focus tasks from **`v2_focus_tasks`** instead, the backend must be changed to use `v2_focus_tasks` (and selection by `max_performance_score` / score_1) for the homework flow. Right now the flow does **not** read from `v2_focus_tasks`.

**Optional:** Backend can return a specific code when no focus task is available (e.g. `NO_FOCUS_TASK_CONFIGURED`) so the frontend can show a clear message instead of an empty block.

---

## 2) Final task (step 3) is empty or not shown

The final task text is generated in **POST /session/<id>/metric-answers** via `openai_service.generate_final_task(...)` and stored in `session.final_task_text`. It is returned in that response as `final_task`.

- If **focus task was null** (see §1), `generate_final_task` still runs with empty `focus_task_title` and `focus_task_prompt`, so the text may be generic but still present.
- If the **UI never shows it**, the frontend may not be reading `final_task` from the metric-answers response, or not reading `session.final_task_text` from **GET /session/status** when `status === final_task_ready`.

**Check:**

- After submitting metric answers, does the **metric-answers** response body contain **`final_task`** with a non-empty string?
- When `session.status === "final_task_ready"`, does **GET /session/status** include **`session.final_task_text`**? The frontend should display that in the “second recording” step.

---

## 3) Recording_2 (second recording) not processed

Possible issues:

- **Session not in `final_task_ready`** — **POST /session/<id>/recording-2** requires `session.status === "final_task_ready"`. If the session is still `task_block` or something else, the backend returns **404** `Session not found or not in final_task_ready`.
- **Frontend not calling the right endpoint** — Confirm the app sends the audio to **POST /v2/homework/session/<session_id>/recording-2** (or the BFF proxy of it).
- **Backend error** — Transcribe, metrics, or DB write can fail (e.g. 500 with `V2_ERROR`). Check backend logs and the response body.

**Check:**

- In Network tab, when the user submits the second recording, find **POST .../recording-2**. Inspect status code and response. On success you get **200** and `recording_id`, `performance_score_2`; session should move to **post_questions**.
- If you get **404**, confirm `session.status` is **final_task_ready** (e.g. from **GET /session/status** before submitting).

---

## Summary

| Symptom | Likely cause | Action |
|--------|---------------|--------|
| Focus task (step 2) empty or “second task” missing | **v2_tasks** empty or no active row | Add active task(s) to **v2_tasks**; confirm admin is editing the table the flow uses. |
| Final task text not shown | Frontend not using `final_task` / `session.final_task_text` | Use metric-answers response and status response; render in step 3. |
| Recording_2 fails or doesn’t advance | Session not `final_task_ready`, or backend error | Check status before upload; check 404/500 and logs for recording-2. |

If you tell us which of the three (“focus task”, “final task”, or “recording_2”) is not working and paste the relevant request URL + response (e.g. **GET task-block** or **POST recording-2**), we can pinpoint the fix.
