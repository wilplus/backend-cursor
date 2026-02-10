# Debug: warm-up task not loading

When the UI shows "Tap Try again to load your task", "Your warm-up task will appear here", or the warm-up task never appears, one of these is happening:

**If both warm-up and focus tasks are missing** even though they exist in the admin panel, use the consolidated checklist: **docs/DEBUG-TASKS-NOT-SHOWING-BFF-JWT.md** (BFF stripping, wrong `user_id` from JWT, status/endpoint logic, and what to paste).

1. **The request the UI is using is not returning `warm_up_task`** (different endpoint / error / session not `warm_up`).
2. **The UI calls the BFF** and the **BFF is dropping/reshaping** the backend payload.
3. **The backend is returning null/empty** for that user/session (no tasks, wrong `user_id` from JWT, session not `warm_up`, DB query failing).

Do the steps below in order.

---

## How to get the response (step-by-step)

Follow this to capture the **request URL** and **JSON response body** so you can paste them for diagnosis.

1. **Open your app** in the browser (e.g. the student homework flow) and **log in** so you can reach the warm-up step.
2. **Open DevTools:**  
   - **Chrome/Edge:** `F12` or `Ctrl+Shift+I` (Windows) / `Cmd+Option+I` (Mac), or right‑click → **Inspect**.  
   - **Safari:** Enable Develop menu (Preferences → Advanced), then **Develop → Show Web Inspector**.
3. **Go to the Network tab** in DevTools (top bar: Elements, Console, **Network**, …).
4. **(Optional)** Click the **Clear** (🚫) button so old requests don’t clutter the list. You can type `status` or `session` in the filter box to narrow results.
5. **Trigger the warm-up screen:**  
   - Navigate to the homework flow until you see the **warm-up step** (the screen where the task should appear but doesn’t).  
   - If you’re already on that screen, refresh the page or tap “Try again” so the app sends the request again.
6. **Find the right request** in the Network list. Look for one of:
   - **Name/Path** containing `session/status` (often a **GET**), or  
   - **Name/Path** containing `session/start` (often a **POST**).  
   The URL might look like `.../api/homework/session/status` (BFF) or `.../v2/homework/session/status` (backend). Click that row.
7. **Get the URL:**  
   - In the **Headers** (or **General**) section you’ll see **Request URL**. Copy the full URL (e.g. `https://app.example.com/api/homework/session/status`).
8. **Get the response body:**  
   - Click the **Response** (or **Preview**) sub-tab for that request.  
   - You should see JSON. **Right‑click in the response area → Copy** (or select all and copy). If your browser only has “Copy response”, use that so you get the full JSON.
9. **Paste both somewhere** (e.g. in your reply or a doc):
   - **URL:** `<paste the Request URL here>`
   - **Response:** `<paste the JSON here>`

With that, anyone can tell you whether the problem is BFF stripping, frontend not rendering, or backend returning null.

---

## 1) Identify the exact request the warm-up screen uses and inspect its JSON

In **DevTools → Network**, when you open the warm-up step, find the request that fires. Commonly one of:

- `GET /api/homework/session/status` (BFF) or `GET /v2/homework/session/status` (backend)
- `POST /api/homework/session/start` or `POST /v2/homework/session/start`

Open it and check:

- **HTTP status is 200** (not 401/403/422).
- Response includes either:
  - top-level **`warm_up_task.text`**, or
  - **`session.warm_up_task_text`**
- **`session.status`** is actually `"warm_up"`.

**Paste here:**

- The **request URL** (so we know BFF vs backend).
- The **full JSON response body**.

That single paste is enough to pinpoint which branch you're in.

---

## 2) If the UI calls `/api/...` (BFF): check if BFF is stripping `warm_up_task`

This is extremely common.

Compare:

- **Browser/BFF:** e.g. `https://app.willonski.com/api/homework/session/status`
- **Backend direct:** `<BACKEND_URL>/v2/homework/session/status`

If the **backend direct** response contains `warm_up_task` but the **BFF** response does not, the fix is in the BFF route: it's returning only `session` (or re-mapping keys) instead of returning the full backend JSON.

---

## 3) If the backend response lacks `warm_up_task` (or it's null): backend edge cases

### A) The user has no warm-up tasks

Run in Supabase:

```sql
select id, text, order_index, max_performance_score
from public.v2_warm_up_tasks
where user_id = '<USER_UUID>'
order by order_index asc;
```

If **0 rows** → backend may return **422** `NO_WARMUP_CONFIGURED`, or it may try to create a default task ("How was your day so far?"). If that default-insert code path fails (missing column, wrong type, RLS), you get null/422.

**Typical causes for default insert failing:** missing `user_id`/`text`/`order_index`/`max_performance_score`; wrong type for `max_performance_score` (use int `1`); RLS blocking INSERT/SELECT on `v2_warm_up_tasks`. Check backend logs for `v2_ensure_default_warm_up_task insert failed for user_id=...`.

### B) JWT verification is producing the wrong `user_id`

If auth/JWT handling was changed (e.g. Flask + Supabase JWT), and `user_id` extraction is wrong (not using `sub`, or a different claim), the backend will query warm-up tasks for the wrong UUID → nothing will show.

**Telltale signs:** response shows session/user info for an unexpected id; admin has warm-up tasks for user A but backend behaves as if querying user B.

**Check:** Add temporary logging (or inspect logs) for JWT `sub` and the resolved `user_id` passed to `v2_get_assigned_warm_up_task(user_id)`.

### C) Session status isn't `warm_up`

In `/session/status`, the backend only computes and returns assigned warm-up when **`session.status === "warm_up"`**; otherwise it uses snapshot fields (`warm_up_task_id`, `warm_up_task_text`). If those snapshot fields were never set (or the session didn’t start properly), you’ll see null.

**Check:** Inspect **`session.status`** in the response. If it’s not `"warm_up"`, that explains why `warm_up_task` may be missing or from a stale snapshot.

### D) DB query failing (schema/cache) but being swallowed

If `v2_get_assigned_warm_up_task` (or the underlying Supabase/PostgREST call) references columns that don’t exist or schema cache is stale, the backend may error and return a fallback/empty result depending on exception handling.

**Check:** Backend logs for PostgREST errors (e.g. **PGRST204** missing column). Run migrations for `v2_warm_up_tasks` and reload schema if using PostgREST.

---

## What I need to finish this in one step

**Paste the actual Network response JSON** from the request the warm-up screen uses, **plus the request URL**. Without that, we’re guessing between BFF stripping vs backend null vs auth/session-state issues.

With that paste, we can tell you exactly where the bug is and what to change (BFF vs Flask vs DB).

---

## Quick reference: what the backend returns

- **GET /v2/homework/session/status** — when `session.status === "warm_up"`, response includes **`warm_up_task: { id, text }`** (and `session` with `warm_up_task_id`, `warm_up_task_text`). Other statuses use session snapshot only.
- **POST /v2/homework/session/start** — returns **`warm_up_task: { id, text }`** or **422** `NO_WARMUP_CONFIGURED`.
- **GET /v2/homework/session/{session_id}/warm-up-task** — returns **`warm_up_task: { id, text }`** or **404**.

If the response **has** `warm_up_task.text` (or non-empty `session.warm_up_task_text`) but the UI still shows a placeholder → **frontend not rendering**: the component must display `response.warm_up_task?.text` or `response.session?.warm_up_task_text` in the warm-up content area (see **docs/FRONTEND-WARM-UP-TASK-DISPLAY.md**).
