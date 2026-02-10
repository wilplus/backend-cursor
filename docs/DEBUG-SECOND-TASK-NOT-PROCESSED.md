# Debug: “Second task” not being processed

“Second task” usually means one of:

1. **Focus task (step 2)** — the task + 3 metric questions after the warm-up recording. User should see a focus task and three questions.
2. **Final task (step 3)** — the AI-generated prompt for the second recording. User should see this text before recording again.
3. **Recording_2** — the second recording upload; “not processed” can mean upload fails, or session never moves to post_questions.

Below: most likely causes and how to fix them.

---

## 1) Focus task (step 2) is null or missing

The homework flow **prefers per-student focus tasks** from **`v2_focus_tasks`** (the ones you add in the admin panel for a student). If the student has at least one focus task with `max_performance_score >= performance_score_1`, one of those is chosen. If the student has **no** rows in `v2_focus_tasks`, or none eligible for their score, the flow falls back to **`v2_tasks`** (global tasks).

- If the student has **no rows in `v2_focus_tasks`** and **no active rows in `v2_tasks`**, then no focus task is selected → `focus_task` is **null**.

**Check per-student (admin-assigned) focus tasks:**

```sql
select id, text, order_index, max_performance_score
from public.v2_focus_tasks
where user_id = '<STUDENT_USER_UUID>'
order by order_index asc;
```

If this returns **0 rows** for that student, add focus tasks for them in the admin panel (or sync from the focus task pool). Then run the migration **`migrations/allow_focus_task_id_in_selected_task_id.sql`** so the session can store the chosen focus task id (it may reference `v2_focus_tasks`, not only `v2_tasks`).

**Check global fallback:**

```sql
select id, title, prompt_text, min_task_score, is_active
from public.v2_tasks
where is_active = true
order by min_task_score asc;
```

If the student has no focus tasks and this also returns **0 rows**, add at least one active task to **`v2_tasks`** or assign focus tasks to the student in the admin panel.

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

## What to paste so we can pinpoint the fix (focus task / default not showing)

When you see **"No focus task available for your current score"** (or the default **"Pay attention to your breathing"** doesn’t show), paste **one** Network response so we can say immediately whether it’s:

- **Frontend treating `id: null` as missing** (most likely) — UI only renders when `focus_task.id` is truthy and hides the default.
- **Backend not returning the default** on that endpoint — response has `focus_task: null` instead of `{ id: null, title: "...", prompt_text: "..." }`.
- **BFF stripping** — BFF returns only part of the body and drops `task_block` or `task_block.focus_task`.

### Which request to capture

The request that **precedes** showing the message is one of:

1. **POST …/recording-1** — Right after the user submits the first recording; the response includes **`task_block`** (with **`focus_task`**). In Network, find the request named **`recording-1`** (or URL containing `recording-1`), click it.
2. **GET …/task-block** — When loading or resuming step 2 (e.g. refresh on the focus step). In Network, find the request whose URL contains **`task-block`**, click it.

### What to paste (you must paste the actual data)

This is an **instruction** for what to paste, **not the paste itself**. To pinpoint **your** bug we need the **actual** request URL + **actual** JSON response from your environment. **Without that paste we cannot distinguish** "backend didn't send default" vs "frontend still checks focus_task incorrectly."

1. **Request URL** — The exact URL from DevTools → Network for the request that **immediately precedes** the message appearing (e.g. `POST https://…/recording-1` or `GET …/task-block`).
2. **Full response body (JSON)** — Copy from the **Response** tab of that request (the entire JSON).

Choose **one**: **POST …/recording-1** (right after first recording completes) **or** **GET …/task-block** (when step 2 loads/resumes).

Paste both in your reply. From that we can tell whether the fix is a **frontend conditional** (e.g. show task when `focus_task` is present, including when `focus_task.id` is null) or a **backend fallback** (ensure default is returned on that path) or **BFF passthrough** (return full `data`, not only `data.session`), and give the exact code change. If your desired behavior is **not to display focus_task at all** on that step, see **docs/PRODUCT-BEHAVIOR-FOCUS-TASK-NOT-DISPLAYED.md** (fix is likely: remove the UI check entirely).

---

## Summary

| Symptom | Likely cause | Action |
|--------|---------------|--------|
| Focus task (step 2) empty or “second task” missing | **v2_tasks** empty or no active row | Add active task(s) to **v2_tasks**; confirm admin is editing the table the flow uses. |
| Final task text not shown | Frontend not using `final_task` / `session.final_task_text` | Use metric-answers response and status response; render in step 3. |
| Recording_2 fails or doesn’t advance | Session not `final_task_ready`, or backend error | Check status before upload; check 404/500 and logs for recording-2. |

If you tell us which of the three (“focus task”, “final task”, or “recording_2”) is not working and paste the relevant request URL + response (e.g. **GET task-block** or **POST recording-2**), we can pinpoint the fix.
