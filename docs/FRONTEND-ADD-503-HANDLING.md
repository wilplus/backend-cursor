# Frontend: add this for admin 503 / Save errors

Paste this into your frontend repo (or hand to the frontend dev) so admin Save errors show the real reason and behavior is correct.

---

## 1. Show the real error when backend returns 503

For admin requests (warm-up-tasks, focus-tasks, post-recording-questions, overrides, etc.), when the response is **503**, show the **backend’s message** in the toast/alert, not only a generic line.

- Read the response JSON: **`detail`** or **`message`** (real error), fallback to **`error`**.
- Example: user should see something like *"PostgREST can't find column max_performance_score on public.v2_warm_up_tasks (PGRST204)"* so they (or you) know what to fix.

```ts
// After fetching, if res.status === 503:
const body = await res.json().catch(() => ({}));
const msg = body.detail ?? body.message ?? body.error ?? "Request failed";
toast.error(msg);  // or your alert/toast API
```

---

## 2. Don’t treat empty lists as an error

For **GET** `/api/admin/students/:id/warm-up-tasks` and **GET** `/api/admin/students/:id/focus-tasks`:

- **200** with **empty array** (`warm_up_tasks: []` or `focus_tasks: []`) is valid (no tasks yet).
- Do **not** show an error toast or banner only because the list is empty.
- Only show an error when the **request** fails (non‑2xx status or network error).

---

## 3. BFF: forward 503 (and body) to the client

- Do **not** convert backend **503** into **500**. Forward the backend’s status and body so the frontend gets 503 and can read `detail` / `message`.
- If the BFF cannot reach the backend, return **502** with e.g. `{ "error": "Backend unreachable" }` so the UI can show a distinct message instead of a generic 500.
