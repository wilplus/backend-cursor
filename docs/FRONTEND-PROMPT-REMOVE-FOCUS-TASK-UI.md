# Frontend prompt: Remove all focus-task UI from the metrics step (step 2)

**Copy this to your frontend repo or paste it into your AI/editor to get the exact edits.**

---

## Context

On the **metrics step** (the screen after the first recording), the student should see **only the 3 metric questions**. Nothing else.

- **context_1** (AI summary of the first recording) is **used by the backend** when defining the final task (step 3) but is **not displayed** at the metrics stage. The API **does not return** `context_short` in the task-block for this step.
- The **focus task** is **stored** and used when generating the final task; it is **not displayed** and **not returned** here.

The task-block payload is **metric_question_1**, **metric_question_2**, **metric_question_3** only. Remove all UI that displays focus task or context_1 (AI commentary) on this step.

---

## What to remove

1. **Any component or block that displays a “focus task”** on the metrics step (the screen after recording 1, before the final recording). For example:
   - A card/section titled “Your task (after first recording)” that shows a focus task title or prompt text.
   - Any UI that reads `task_block.focus_task` (or `response.task_block?.focus_task`) and renders its `title` or `prompt_text`.

2. **The “No focus task available” message.** Remove the entire block that shows:
   - *“No focus task available for your current score. You can still answer the questions below and continue, or start over. Contact your coach if this persists.”*  
   (or any variant of that string). Search the codebase for **“No focus task available”** or **“focus task available”** and remove that conditional and the message.

3. **Any gating that depends on `focus_task`.** Do not block or warn the user based on whether `task_block.focus_task` is present or null. The user should always be able to proceed to the 3 metric questions after recording 1.

4. **Any code that reads `task_block.focus_task`** (or `response.task_block?.focus_task`). The API no longer sends this field; you can delete variables and conditionals that reference it for the metrics step.

5. **Any component or block that displays context_1 / “AI commentary”** (e.g. a summary of the first recording) on the metrics step. context_1 is not displayed at this stage; the API does not return `context_short` in the task-block.

6. **Types or interfaces** that require `focus_task` or `context_short` inside `task_block` for this flow. Update them so `task_block` has only `metric_question_1`, `metric_question_2`, `metric_question_3`.

---

## What the metrics step (step 2) should show

After the first recording, the screen should show **only the 3 metric questions**:

- Use `task_block.metric_question_1`, `task_block.metric_question_2`, `task_block.metric_question_3` from **POST …/recording-1** or **GET …/task-block**. Render the question text and input fields; on submit, send the answers via **POST …/metric-answers**.

Do **not** show context_1 / AI commentary, and do **not** show a focus task card or “No focus task available…” message. The API returns only the 3 questions for this step.

---

## API contract (for reference)

- **POST /v2/homework/session/:sessionId/recording-1**  
  Response includes `task_block`: `{ metric_question_1, metric_question_2, metric_question_3 }` only. No `context_short`, no `focus_task`.

- **GET /v2/homework/session/:sessionId/task-block**  
  Response includes `task_block`: `{ metric_question_1, metric_question_2, metric_question_3 }` only. No `context_short`, no `focus_task`.

context_1 is used by the backend when generating the final task (step 3) but is not sent to the client for the metrics step.

---

## Checklist

- [ ] Removed any component that displays a focus task (title/prompt) on the metrics step.
- [ ] Removed the “No focus task available…” message and its conditional.
- [ ] Removed any gating that requires or checks `focus_task` to proceed.
- [ ] Removed or updated code that reads `task_block.focus_task` (or equivalent).
- [ ] Updated types/interfaces so `task_block` does not require `focus_task` for this flow.
- [ ] Removed any display of context_1 / AI commentary on the metrics step.
- [ ] Metrics step now shows **only** the **3 metric questions** (metric_question_1/2/3). No context_1, no focus task.

---

## Search suggestions

To find the code to change, search for:

- `"No focus task available"` or `'No focus task available'`
- `focus_task` (especially `task_block.focus_task`, `response.task_block?.focus_task`)
- `focusTask` (camelCase variable)
- “Your task (after first recording)” or similar heading text
- Components or screens that render the “step 2” or “metrics” or “task block” step after recording 1

Then remove or refactor so that step only renders the **three metric questions**. Do not render context_1 or focus task.
