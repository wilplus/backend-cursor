# Select Focus Tasks modal — Add button implementation

If "Add" in the **Select Focus Tasks** modal does nothing or the new task never appears in the pool, wire it like this.

## 1. Ensure the BFF route exists (correct path)

The frontend calls **`/api/admin/tasks`**, so the route file **must** be at:

- **File:** `src/app/api/admin/tasks/route.ts`  
  → This makes the URL **/api/admin/tasks** (correct).

**Wrong:** `src/app/api/v2/admin/tasks/route.ts`  
→ That would make the URL **/api/v2/admin/tasks**. The admin client does **not** use `/api/v2/...`; it uses `/api/admin/...`, so you get 404 if the route is under `api/v2`.

- **Copy from:** `docs/frontend-admin-panel/api-routes/tasks-route.ts` (in this repo).
- The route forwards to your backend `POST /v2/admin/tasks`. Without this file at **api/admin/tasks**, the browser request gets 404.

## 2. Add button: call the API and refresh the list

When the user types a task title and clicks **Add**:

1. **POST** to `/api/admin/tasks` with body `{ "title": "<trimmed input>" }`.
2. On **success (201)**: take the returned `task` from the response, add it to the list of tasks in state (or refetch the full task list), and clear the input.
3. On **error**: show a toast or message (e.g. "Failed to add task") and optionally log the response.

### Example handler (React)

Assume you have:

- `newTaskTitle` — state for the input (e.g. "Pay an attention to your intonation")
- `setTasks` — setter for the list of tasks shown in the modal
- `loadTasks` — function that fetches tasks (e.g. `adminApi.getTasks()` or `fetch("/api/admin/tasks").then(r => r.json())`)

```ts
async function handleAddFocusTask() {
  const title = newTaskTitle.trim();
  if (!title) return;

  setAdding(true); // optional: disable button / show loading
  try {
    const res = await fetch("/api/admin/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include", // send cookies if you use session-based auth
      body: JSON.stringify({ title }),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      toast.error(data?.error || data?.code || "Failed to add task");
      return;
    }

    // Success: add the new task to the list so it appears in the pool
    const task = data.task;
    if (task) setTasks((prev) => [...prev, task]);
    setNewTaskTitle("");
    toast.success("Task added");
  } catch (e) {
    toast.error("Failed to add task");
  } finally {
    setAdding(false);
  }
}
```

Wire the **Add** button to `handleAddFocusTask` and the input to `newTaskTitle` / `setNewTaskTitle`.

### If you use the admin API client

```ts
import { adminApi } from "@/lib/api/admin-client";

async function handleAddFocusTask() {
  const title = newTaskTitle.trim();
  if (!title) return;

  try {
    const { task } = await adminApi.createTask({ title });
    setTasks((prev) => [...prev, task]);
    setNewTaskTitle("");
    toast.success("Task added");
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "Failed to add task");
  }
}
```

## 3. Backend contract (for reference)

- **Request:** `POST /api/admin/tasks` (BFF) → proxies to `POST /v2/admin/tasks` (backend).
- **Body:** `{ "title": "string" }` (optional: `prompt_text`, `min_task_score`, `max_task_score`). Backend defaults `prompt_text` to `title` if omitted.
- **Response (201):** `{ "task": { "id": "...", "title": "...", "prompt_text": "...", ... } }`.
- **Errors:** 400 if `title` is empty, 401 if not logged in, 403 if not admin, 500 on server error.

## 4. Quick checks

- **Network tab:** When you click Add, do you see a **POST** request to **/api/admin/tasks**? If not, the button is not calling the API.
- **Status:** Is the response **201**? If **404**, the BFF route is missing. If **401/403**, fix auth. If **400**, body might be wrong (send `{ title: "..." }`).
- **After 201:** Does your code add `data.task` to the list or refetch tasks? If not, the pool will still show "No items in pool yet."
