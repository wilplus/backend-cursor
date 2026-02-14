# Frontend: Default warm-up task (summary)

## What the backend does

Users who have **no warm-up tasks assigned** (e.g. new users) get a **default warm-up** automatically. The backend creates one task per user with the text:

**"How was your day so far?"**

So new users can start the homework flow without a coach assigning a warm-up first. The API will normally return `warm_up_task: { id, text: "How was your day so far?" }` from start/status and GET warm-up-task.

---

## Frontend fallback (recommended)

When the warm-up from the API is **missing, null, or empty** (`warm_up_task` / `warm_up_task_text` null, `{}`, or `text: ""`), the **frontend** should show the same default so the flow never blocks:

| Backend returns | Frontend shows |
|-----------------|----------------|
| No / null / empty warm-up | "How was your day so far?" |
| `warm_up_task: { text: "…" }` (non-empty) | The returned text |

**Default text:** `"How was your day so far?"`

This covers the rare case where default creation fails (backend returns 200 but with empty warm-up) and keeps the contract simple: empty = show default.

---

## API contract

- **POST `/v2/homework/session/start`** — Returns `warm_up_task: { id, text }` for new users (backend creates default). If you ever receive `warm_up_task: null` or empty, show the default.
- **GET `/v2/homework/session/status`** — Same: if `warm_up_task` / warm-up fields are missing or empty, show the default for step 1.
- **GET `/v2/homework/session/:id/warm-up-task`** — Same fallback when response has no or empty text.

No API change is required for the frontend fallback; the backend already returns a real warm-up for new users. The fallback is for robustness.

---

## Edge case: 422 NO_WARMUP_CONFIGURED

If the backend **cannot** create the default (e.g. DB error), it returns **422** with `code: "NO_WARMUP_CONFIGURED"` and message to contact coach. Keep handling that as today (e.g. show "No warm-up configured", step 0, contact coach).

---

## Summary

- **Backend:** Creates a default warm-up task for users with none; API usually returns `warm_up_task` with "How was your day so far?"
- **Frontend:** When warm-up is missing or empty, show **"How was your day so far?"** so the user is never blocked. Keep 422 NO_WARMUP_CONFIGURED handling for the rare failure case.
