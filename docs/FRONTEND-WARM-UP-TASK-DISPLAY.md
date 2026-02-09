# Frontend: How to display the warm-up task text

**Goal:** Show the actual warm-up prompt (e.g. "How was your day so far?") in the warm-up step, not only the label "Warm-up task" and not the placeholder "Your warm-up task will appear here."

---

## Where the data comes from (backend)

- **GET /v2/homework/session/status** — Response includes **`warm_up_task`** when there is an active session:
  - `warm_up_task: { id: string, text: string }` (e.g. `text: "How was your day so far?"`)
  - Or `warm_up_task: null` if none.
- **POST /v2/homework/session/start** — Response includes the same **`warm_up_task: { id, text }**.

The backend fills `warm_up_task` from the **v2_warm_up_tasks** table (and creates a default task if the user has none).

---

## What the frontend should do

### 1. Read the task text from the API response

After calling **GET /session/status** or **POST /session/start**, use:

```ts
// Preferred: top-level warm_up_task (returned by backend)
const taskText = response.warm_up_task?.text;

// Fallback: from raw session (status returns session object)
const taskTextFallback = response.session?.warm_up_task_text;

// Final fallback for empty or missing
const displayText = (taskText || taskTextFallback || "").trim()
  || "Your warm-up task will appear here.";
```

### 2. Render it in the warm-up step UI

- **Label:** Keep the heading "Warm-up task".
- **Content:** In the same box (e.g. the orange/task area), render **`displayText`** so the user sees the real prompt, e.g.:
  - *"How was your day so far?"*

Do **not** show only "Warm-up task" with no content below it. The user must see the sentence they should speak to.

### 3. When to refresh

- On **GET /session/status** (e.g. page load or resume): set state from `response.warm_up_task` (or `response.session.warm_up_task_text`) and render it.
- On **POST /session/start**: set state from `response.warm_up_task` and render it.

If the UI shows "Your warm-up task will appear here.", it usually means the frontend is not reading `response.warm_up_task.text` (or the request failed / returned null). Check that you use the response from status or start and that you render `warm_up_task.text` in the task content area.

---

## Example (React)

```tsx
// After fetch:
const { session, warm_up_task } = statusResponse;
const warmUpText = warm_up_task?.text?.trim() || session?.warm_up_task_text?.trim() || "Your warm-up task will appear here.";

// In JSX (warm-up step):
<div className="warm-up-task-area">
  <h3>Warm-up task</h3>
  <p>{warmUpText}</p>
</div>
```

---

## Quick checklist

| Item | Action |
|------|--------|
| Use `response.warm_up_task` | From GET /session/status and POST /session/start. |
| Prefer `warm_up_task.text` | That is the prompt from the DB. |
| Fallback | `session.warm_up_task_text` or placeholder string. |
| Render in task area | Show the text in the orange/task box, not only the "Warm-up task" label. |
