# Product behavior: Focus task is not displayed on the metrics step

The focus task is **chosen and stored** after recording 1 for use when generating the **final_task** (step 3). It is **not** shown to the user on the metrics step (step 2). The “No focus task available…” message and any focus-task card on that step are **wrong product behavior** and should be removed.

---

## Intended flow

1. **After recording 1:** Backend **chooses** a focus task (per-student, global, or default “Pay attention to your breathing”) and **stores** it on the session (e.g. `selected_task_id` or equivalent). It is used later when generating `final_task_text`.
2. **Metrics step (step 2):** The UI shows **only the 3 metric questions**. context_1 and focus_task are not displayed (API returns only the 3 questions). **Nothing about focus_task** is displayed. The user does not see a “focus task card” or “No focus task available…” on this step.
3. **When generating final task:** Backend uses **context_1** (context_short), the stored focus task (or default), and metric answers to produce `final_task_text`. So context_1 is taken into account when defining the task; it is not shown on the metrics step.

So: **focus_task is for backend use only at metrics time**; the UI must not depend on it for display or gating on the metrics step.

---

## Why you see “No focus task available…”

Current UI logic effectively does:

- “After recording 1 / before metrics, we should have a focus task to show.”
- Backend returns `focus_task: null` or a default with `id: null`, and the UI treats it as missing.
- UI shows the warning.

Per the intended behavior above, **focus_task should not be displayed at all** on that step—only chosen and stored for later. So the fix is to change the UI (and optionally simplify what the backend returns for that step), not to make the default focus task “visible” there.

---

## What needs to change

### A) Frontend (required)

After recording 1, the metrics step should render:

1. **AI commentary** (based on context_1 / `context_short`)
2. **The 3 metric questions**

and **nothing** about focus_task.

**Remove or disable:**

- Any “Focus task” card/component on that step
- The “No focus task available for your current score…” fallback message on that step
- Any gating that “requires” `focus_task` to proceed

**Acceptance criteria:**

- After recording 1, the UI does **not** read or display `task_block.focus_task` on that screen.
- The UI **never** shows “No focus task available…” on that screen.
- The UI proceeds to the 3 metric questions regardless of whether `focus_task` is present or null.

### B) Backend (already aligned with Design 1)

The backend already implements **Design 1: choose + store right after recording 1.**

- When recording 1 is completed, the backend picks a focus task (per-student → global → default “Pay attention to your breathing”) and stores it (e.g. `selected_task_id` on `v2_sessions`).
- When **POST metric-answers** runs, it resolves the stored task (or uses the default) and passes it to `generate_final_task` to produce `final_task_text`. So the default is used internally when no task is stored; the UI does not need to receive it at metrics time for display.

The backend **does not** include `focus_task` in **POST recording-1** or **GET task-block** responses. It is stored only (`selected_task_id` on the session) and used when generating `final_task_text`. The metrics step payload is **context_short** + **metric_question_1/2/3** only.

---

## Where is focus_task stored? (backend)

- **Storage:** **`v2_sessions.selected_task_id`** — UUID of the chosen task (from `v2_focus_tasks` or `v2_tasks`). Set when recording 1 completes (POST recording-1).
- **Default:** When no task is chosen, `selected_task_id` stays **null**. On POST metric-answers the backend uses **`DEFAULT_FOCUS_TASK_TEXT`** ("Pay attention to your breathing") when generating `final_task_text`.
- **Flow:** Choose + store on recording-1 completion (already implemented). Use stored task or default only when generating final task; do not show focus_task on the metrics step.

---

## What to paste to get exact edits (you must paste the actual data)

The instructions below are **not the paste itself**. To pinpoint **your** bug we need the **actual** request URL + **actual** JSON response from your environment. **Without that paste we cannot distinguish** "backend didn't send default" vs "frontend still checks focus_task incorrectly."

To get **exact** frontend (and if needed backend) edits:

1. **Network request(s) right after recording 1**  
   Paste the **URL(s)** of the request(s) that run immediately after recording 1 finishes. Usually one of:
   - `POST .../recording-1`
   - `GET .../task-block`
   - `GET .../session/status`
   - `POST .../metric-questions` / `POST .../metric-answers`

2. **Where the warning is rendered**  
   Point to the **component/page** (file path) or paste the **snippet** where the string **“No focus task available”** (or the full message) appears. With that we can give the exact conditional to remove or change.

Paste the **exact response that immediately precedes the message appearing** (request that runs right before you see the message). Choose one of: **POST …/recording-1** or **GET …/task-block**. With that actual URL + JSON we can tell you immediately if it's frontend treating `focus_task.id === null` as missing, backend not returning the default, or BFF stripping.

---

## Two parallel tracks

**A) Debug the current message** — Paste the actual URL + full response JSON for the request right before the message appears. Then we can say exactly why it appears.

**B) Fix for desired behavior (no focus_task displayed)** — The correct behavior is: frontend does **not** render focus_task and **never** shows "No focus task available…" on that screen. The likely fix is: **remove this UI check entirely**. Find the component that contains that string and change the logic from "if no focus_task show warning" to "don't check focus_task here at all; always show commentary + metric questions." If you provide the file or snippet where that string lives, we can give the exact edit.

---

## Quick fix (fastest path)

1. **Frontend:** Remove the focus-task display requirement from the post–recording-1 metrics screen:
   - Delete the block that checks `focus_task` and shows the “No focus task available…” warning.
   - Always render commentary + metric questions; do not render a focus task card on that step.

2. **Backend:** No change required for “not displayed.” The backend already stores the chosen focus task (or default) and uses it when generating the final task. You do **not** need to send the focus task to the UI for display at metrics time; if you do send it (e.g. in `task_block`), the frontend should ignore it on that step.

---

## DB check to confirm focus_task is stored

After recording 1, the session should have the chosen task stored. Example:

```sql
select id, user_id, selected_task_id, context_short
from public.v2_sessions
where user_id = '<STUDENT_UUID>'
order by created_at desc
limit 5;
```

`selected_task_id` (or your snapshot columns) should be set when a focus task (or default) was chosen. For the default, `selected_task_id` may be null and the backend uses `DEFAULT_FOCUS_TASK_TEXT` when generating the final task.
