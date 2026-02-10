# Frontend: What to do so warm-up and focus tasks show

Checklist so the **warm-up task** and **focus task** actually appear in the student flow. Backend returns the data; the frontend must read and render it (and the BFF must pass it through).

---

## 1. Warm-up step (step 1)

### 1.1 Call the right endpoint

- **Resume / load:** `GET /api/homework/session/status` (or direct `GET /v2/homework/session/status`).
- **Start new session:** `POST /api/homework/session/start` (or direct `POST /v2/homework/session/start`).

### 1.2 Read the task text from the response

Use the **full response object**, not only `session`:

```ts
// After GET status or POST start:
const taskText =
  response.warm_up_task?.text?.trim() ||
  response.session?.warm_up_task_text?.trim() ||
  "Your warm-up task will appear here.";
```

### 1.3 Render it in the UI

- **Heading:** e.g. "Warm-up task".
- **Content (the actual prompt):** Render **`taskText`** in the same card/area (e.g. the main task box). The user must see the sentence they should speak to (e.g. *"How was your day so far?"*), not only the label or a permanent placeholder.

If the user always sees "Your warm-up task will appear here.", the frontend is not using `response.warm_up_task?.text` (or the BFF is stripping it — see §4).

### 1.4 Handle "no warm-up" (422)

If **POST /session/start** (or status) returns **422** and `body.code === "NO_WARMUP_CONFIGURED"`:

- Do **not** show the recorder flow.
- Show a message like: *"No warm-up tasks are configured for your account. Please contact your coach to get started."*
- Offer "Contact coach" / "Log out" or "Back to dashboard".

---

## 2. Metrics step (step 2 — after first recording)

**Product behavior:** The focus task is **not displayed** on this step; it is chosen and stored for use when generating the final task (step 3). Do **not** show a focus task card or "No focus task available…" here. See **docs/PRODUCT-BEHAVIOR-FOCUS-TASK-NOT-DISPLAYED.md**.

### 2.1 What to show on step 2

Show **only** (1) **AI commentary** from `task_block.context_short` and (2) the **3 metric questions** from `task_block.metric_question_1/2/3`. Do **not** show a focus task card or "No focus task available…". The API no longer returns `focus_task`. See **docs/FRONTEND-PROMPT-REMOVE-FOCUS-TASK-UI.md** for a removal prompt.

**Data source when the user is in step 2** (`session.status === "task_block"`):

- **Right after first recording:** In the **POST /session/&lt;sessionId&gt;/recording-1** response, inside **`task_block.focus_task`**:
  - `task_block.focus_task: { id, title, prompt_text }` or `null`.
- **On resume / refresh on step 2:** From **GET /api/homework/session/&lt;sessionId&gt;/task-block** (or direct **GET /v2/homework/session/&lt;sessionId&gt;/task-block**). Response shape:
  - `task_block: { context_short, focus_task, metric_question_1, metric_question_2, metric_question_3 }`
  - `focus_task: { id, title, prompt_text }` or `null`.

### 2.2 Read the focus task

After **POST recording-1**:

```ts
const focusTask = response.task_block?.focus_task;
const title = focusTask?.title ?? "";
const promptText = focusTask?.prompt_text ?? "";
// Display: e.g. title as heading, promptText as body (or combine)
```

When loading step 2 (e.g. from **GET task-block**):

```ts
const focusTask = response.task_block?.focus_task;
const title = focusTask?.title ?? "";
const promptText = focusTask?.prompt_text ?? "";
```

### 2.3 Render it in the UI

- Show **title** and/or **prompt_text** in the “Your task (after first recording)” area.
- The backend may send a **default focus task** when there is no other suited option (e.g. new students): `focus_task: { id: null, title: "Pay attention to your breathing", prompt_text: "Pay attention to your breathing" }`. Render it the same way as any other focus task (treat `id` as optional).
- Only if **`focus_task` is null**, show the message: *"No focus task available for your current score. You can still answer the questions below and continue…"* and still show the three metric questions.

### 2.4 When to call GET task-block

- When **`session.status === "task_block"`** and the user lands on step 2 (e.g. after refresh or deep link), call **GET /api/homework/session/&lt;sessionId&gt;/task-block** to get **context_short**, **focus_task**, and the three metric questions. Use that to populate the step 2 screen.

---

## 3. Final task (step 3)

- After **POST /session/&lt;sessionId&gt;/metric-answers**, the response includes **`final_task`** (the AI-generated prompt for the second recording).
- Store it and show it on the “Final task” / recording-2 screen. If you also get **GET /session/status** and `session.status === "final_task_ready"`, you can use **`session.final_task_text`** as a fallback for the displayed prompt.

---

## 4. BFF: pass through the full response

If the student app calls **/api/homework/…** (BFF), the BFF must return the **entire** backend JSON, not only part of it.

**Wrong (strips warm_up_task / focus_task):**

```ts
return NextResponse.json(data.session);
```

**Correct:**

```ts
return NextResponse.json(data);
```

So the client receives **`{ session, warm_up_task?, has_active_session?, … }`** from status/start, and **`{ task_block }`** from task-block. Check every BFF route that proxies homework (status, start, task-block, recording-1, metric-answers) and ensure you return **`data`** (or the full shape the backend sends), not only a subset.

---

## 5. Quick checklist

| Step | Action |
|------|--------|
| Warm-up | Read `response.warm_up_task?.text` (or `session.warm_up_task_text`) and render it in the task content area. |
| Warm-up | Handle 422 `NO_WARMUP_CONFIGURED`: show message, no flow. |
| Focus (step 2) | After recording-1, read `response.task_block?.focus_task` and show `title` / `prompt_text`. |
| Focus (step 2) | On load/resume when status is `task_block`, call GET task-block and render `task_block.focus_task` and the 3 questions. |
| Focus (step 2) | If `focus_task` is null, show “No focus task available…” and still show the 3 questions. |
| Final (step 3) | Show `response.final_task` (or `session.final_task_text`) on the recording-2 screen. |
| BFF | Return `NextResponse.json(data)` so `warm_up_task` and `task_block` are not dropped. |

---

## What to paste if the default focus task still doesn’t show

If you still see **"No focus task available"** and expect **"Pay attention to your breathing"** to appear, paste **one** Network response so we can pinpoint the fix:

- **Which request:** The one that loads the focus step — either **POST …/recording-1** (after first recording) or **GET …/task-block** (when loading/resume step 2). In DevTools → Network, find **`recording-1`** or **`task-block`**, click it.
- **What to paste:** The **Request URL** and the **full Response body (JSON)**. We need to see **`task_block.focus_task`** (or that it’s missing).

From that we can tell immediately whether it’s: **frontend treating `id: null` as missing**, **backend not returning the default**, or **BFF stripping**, and give the exact code change. See **docs/DEBUG-SECOND-TASK-NOT-PROCESSED.md** § “What to paste so we can pinpoint the fix”.

---

## References

- **Remove focus-task UI from metrics step (copy-paste prompt):** `docs/FRONTEND-PROMPT-REMOVE-FOCUS-TASK-UI.md`
- **Focus task not displayed on metrics step (product behavior):** `docs/PRODUCT-BEHAVIOR-FOCUS-TASK-NOT-DISPLAYED.md`
- **Warm-up display detail:** `docs/FRONTEND-WARM-UP-TASK-DISPLAY.md`
- **Guardrails (422 handling, metric answers):** `docs/FRONTEND-BACKEND-HOMEWORK-GUARDRAILS.md`
- **When tasks still don’t show (BFF, JWT, status):** `docs/DEBUG-TASKS-NOT-SHOWING-BFF-JWT.md`
