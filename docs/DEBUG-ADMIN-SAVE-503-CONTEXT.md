# Debug context: Admin Save button / 503 on warm-up-tasks and focus-tasks

**Use this document when asking other LLMs or developers for help debugging the admin "Save" / 503 issue.**

---

## 1. Problem summary

- **Symptom:** In the admin panel (student profile), the **Save** button does not persist changes. When creating or syncing **warm-up tasks** or **focus tasks**, the UI shows errors and the browser gets **HTTP 503** from the API.
- **User reports:** "The save button doesn't work"; "the selection works!" (typing and selecting in the modal work; the failure happens when saving).
- **Observed errors:**
  - **Warm-up tasks:** Toast/alert: "Failed to create warm-up task. Check v2_warm_up_tasks table exists." and/or "v2_warm_up_tasks table missing or sync failed." Console: `503` on `https://app.willonski.com/api/admin/students/<STUDENT_ID>/warm-up-tasks`.
  - **Focus tasks:** Toast: "Failed to create focus task. Run migrations/v2_focus_tasks.sql if not done." Console: `503` on `.../focus-tasks`.
- **503** is returned **by design** when the backend catches a DB (or other) error so the server does not return 500; the **real** error is in the response body (`detail` or `message`).

---

## 2. Architecture

- **Frontend:** Admin UI at `app.willonski.com` (Next.js or similar). Student profile page with sections: Warm-up Tasks, Focus tasks, Post-Recording Questions, Metrics, Speaker Profile. Each section has Add/Edit/Delete or Save.
- **BFF:** Requests go to `https://app.willonski.com/api/admin/...` (same origin). The BFF proxies to the Flask backend with admin auth.
- **Backend:** Flask app exposing `/v2/admin/...` routes. Uses **Supabase** (Postgres) via `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
- **Database:** Supabase (Postgres). Tables involved: `v2_warm_up_task_pool`, `v2_warm_up_tasks`, `v2_focus_task_pool`, `v2_focus_tasks`, `v2_post_recording_questions`, `v2_student_overrides`, plus `auth.users`.

---

## 3. What is already implemented

### Backend (Flask, this repo)

- **Routes:**
  - **Warm-up tasks:** `GET/POST/PUT/DELETE /v2/admin/students/<user_id>/warm-up-tasks` and `.../warm-up-tasks/<task_id>`; pool: `GET/POST/PUT/DELETE /v2/admin/warm-up-task-pool` and `.../<pool_id>`.
  - **Focus tasks:** `GET/POST/PUT/DELETE /v2/admin/students/<user_id>/focus-tasks` and `.../focus-tasks/<task_id>`; pool: `GET/POST/PUT/DELETE /v2/admin/focus-task-pool` and `.../<pool_id>`.
  - **Post-recording questions:** `GET/POST/PUT/DELETE /v2/admin/post-recording-questions` and `.../<question_id>`. Student overrides (including `assigned_post_question_ids`) via `PUT /v2/admin/students/<user_id>/overrides`.
- **Error handling:** All these endpoints catch exceptions and return **503** with JSON `{ "error": "...", "detail": "<exception message>", "message": "..." }` instead of 500. GET list endpoints return **200** with empty arrays (`[]`) on error so the page can load.
- **DB layer:** `services/db.py` has methods for warm-up and focus tasks (e.g. `v2_get_warm_up_tasks`, `v2_insert_warm_up_task`, `v2_get_focus_tasks`, `v2_insert_focus_task`, sync-from-pool, pool CRUD). Tables used: `v2_warm_up_tasks`, `v2_warm_up_task_pool`, `v2_focus_tasks`, `v2_focus_task_pool`.

### Migrations (SQL)

- **Focus tasks:** `migrations/v2_focus_tasks.sql` creates `v2_focus_task_pool` and `v2_focus_tasks`. User confirmed this migration was run and focus-tasks table existence was verified; focus-tasks may work in some environments but 503 can still occur (e.g. wrong DB, RLS, or other error).
- **Warm-up tasks:** Tables are defined in `migrations/v2_schema_unified.sql` (section 6: `v2_warm_up_task_pool`, `v2_warm_up_tasks`). Optional: `migrations/v2_warm_up_task_pool.sql`. The column `max_performance_score` on `v2_warm_up_tasks` may be added in a separate migration (e.g. `v2_all_in_one.sql`); if missing, inserts can fail with "column does not exist".

### Docs (this repo)

- **docs/DEBUG-503-FOCUS-TASKS.md** – How to read the real error from 503 response, verification checklist, curl example for focus-tasks.
- **docs/DEBUG-503-WARM-UP-TASKS.md** – Same for warm-up: which migrations to run, table check query, optional `max_performance_score` ALTER.
- **docs/PROMPT-FRONTEND-FOCUS-TASKS-PASTE.md** – Frontend integration (BFF paths, response keys, what to show on 503).

---

## 4. What to verify when debugging

1. **Same database:** The migration must be run in the **same** Supabase project the backend uses (env: `SUPABASE_URL`). If the backend points to a different project or DB, tables won’t exist there.
2. **Tables exist:** In Supabase SQL Editor, run:
   - Focus: `SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_focus_tasks');`
   - Warm-up: same for `v2_warm_up_tasks` and `v2_warm_up_task_pool`.
3. **Real error:** In browser DevTools → Network → failing request (e.g. `warm-up-tasks` or `focus-tasks`) → **Response** tab. The JSON body contains `detail` or `message` with the actual exception (e.g. "relation ... does not exist", "permission denied", "column ... does not exist"). Use that to fix the root cause.
4. **BFF → backend:** From the machine that runs the BFF, `curl -H "Authorization: Bearer <admin_token>" "<BACKEND_URL>/v2/admin/students/<id>/warm-up-tasks"` should return 200 and JSON. If this fails, the BFF cannot reach the backend or auth is wrong.
5. **Warm-up column / PGRST204:** If the error is **`PGRST204`: PostgREST can't find column `max_performance_score` on `public.v2_warm_up_tasks`**, the table exists but the column is missing (or PostgREST schema cache is stale). Add the column in Supabase, then run `NOTIFY pgrst, 'reload schema';` so PostgREST picks it up. Full steps: **docs/DEBUG-503-WARM-UP-TASKS.md** (section “PGRST204”).

---

## 5. Key files (backend repo)

| Purpose | Path |
|--------|------|
| Warm-up + focus routes | `routes/v2_routes.py` (search for `warm-up-tasks`, `focus-tasks`) |
| DB access | `services/db.py` (search for `v2_get_warm_up_tasks`, `v2_insert_focus_task`, etc.) |
| Focus tables migration | `migrations/v2_focus_tasks.sql` |
| Warm-up tables (full v2 schema) | `migrations/v2_schema_unified.sql` (section 6) |
| Warm-up pool only | `migrations/v2_warm_up_task_pool.sql` |
| Debug focus 503 | `docs/DEBUG-503-FOCUS-TASKS.md` |
| Debug warm-up 503 | `docs/DEBUG-503-WARM-UP-TASKS.md` |
| "Confirm selection" doesn't work (warm-up) | `docs/DEBUG-WARM-UP-CONFIRM-SELECTION.md` |

---

## 6. Reproducing the issue

1. Log in as admin at `app.willonski.com`.
2. Open a student profile (e.g. Students → click a student).
3. **Warm-up:** Click "+ Add" under Warm-up Tasks, enter task text and max score, click Save. Or use "Manage list" and sync. Observe 503 and toast "v2_warm_up_tasks table missing or sync failed" or "Check v2_warm_up_tasks table exists."
4. **Focus:** Click "+ Add" under Focus tasks, enter task text and max score, click Save. Observe 503 and toast about migrations if the backend returns 503.
5. In DevTools → Network, select the failed request and read the **Response** body for `detail` / `message`.

---

## 7. Summary for other LLMs

- **Problem:** Admin Save for warm-up tasks and/or focus tasks fails with **503** and messages about missing tables or failed sync.
- **Backend** intentionally returns 503 with JSON `{ error, detail, message }` on any exception (no 500). The **real** cause is in `detail` or `message`.
- **Likely causes:** (1) Tables `v2_warm_up_tasks` / `v2_warm_up_task_pool` or `v2_focus_tasks` / `v2_focus_task_pool` missing in the DB the backend uses. (2) Wrong Supabase project (backend env vs where migration was run). (3) Missing column on `v2_warm_up_tasks` (e.g. `max_performance_score`). (4) RLS or permissions blocking insert/update.
- **Next steps:** Inspect 503 response body for `detail`; verify tables (and column) in the DB pointed to by `SUPABASE_URL`; run the relevant migrations if missing; check RLS/policies if the error mentions permission.

---

## 8. What to add in the frontend

Hand this to the frontend (or paste into the frontend repo) so errors are clearer and behavior is correct:

### Show the real error on 503

When any admin request (warm-up-tasks, focus-tasks, post-recording-questions, etc.) returns **503**, read the response JSON and show the **actual** reason in the toast/alert:

- Prefer **`response.detail`** or **`response.message`** if present; fallback to **`response.error`**.
- Example: instead of only "Failed to create warm-up task. Check v2_warm_up_tasks table exists.", show also the backend’s message, e.g. "PostgREST can't find column max_performance_score on public.v2_warm_up_tasks (PGRST204)" so the user or dev knows what to fix.

```ts
// Example (adapt to your API client):
const body = await res.json().catch(() => ({}));
const msg = body.detail ?? body.message ?? body.error ?? "Request failed";
toast.error(msg);
```

### Don’t treat empty list as an error

For **GET** `.../warm-up-tasks` and **GET** `.../focus-tasks`, **200** with an empty array (`warm_up_tasks: []` or `focus_tasks: []`) is valid (no tasks yet). Do **not** show an error toast or banner only because the list is empty. Only show an error when the request fails (non‑2xx or network error).

### BFF: forward 503 and body

The BFF should **not** convert backend **503** into **500**. Forward the backend’s status code and response body so the frontend receives 503 and can read `detail` / `message`. If the BFF can’t reach the backend, returning **502** with a body like `{ "error": "Backend unreachable" }` is better than 500 so the UI can show a distinct message.
