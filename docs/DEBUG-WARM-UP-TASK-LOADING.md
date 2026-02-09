# Debug: warm-up task not loading

When the UI shows "Tap Try again to load your task" or the warm-up task never appears, check the following.

---

## 1. What the frontend calls

- **POST /v2/homework/session/start** — returns `warm_up_task: { id, text }` or **422** `NO_WARMUP_CONFIGURED`.
- **GET /v2/homework/session/{session_id}/warm-up-task** — returns `warm_up_task: { id, text }` or **404** `SESSION_NOT_FOUND` / `NO_WARM_UP`.
- **GET /v2/homework/session/status** — returns the raw session; the session row has `warm_up_task_id` and `warm_up_task_text` (may be null until start or warm-up-task has been used).

If the warm-up "doesn't load", the frontend is usually calling one of these and getting an error or empty data.

---

## 2. Backend causes (in order of likelihood)

### A. Default task insert fails (DB)

When the user has **no** rows in `v2_warm_up_tasks`, the backend tries to insert the default task *"How was your day so far?"*. If that insert fails:

- You get **422** `NO_WARMUP_CONFIGURED` or **404** `NO_WARM_UP`, and
- Backend logs: `v2_ensure_default_warm_up_task insert failed for user_id=... : <error>`.

**Typical causes:**

- **Missing column:** `v2_warm_up_tasks` must have `user_id`, `text`, `order_index`, and `max_performance_score`. If `max_performance_score` or `order_index` is missing, run the migration that adds them (e.g. `migrations/v2_add_max_performance_score_to_tasks.sql` or the warm-up section of your schema).
- **Wrong type:** We send `max_performance_score: 1` (int). If your column is something other than integer/numeric, you may need to alter the column or adjust the insert.
- **RLS (Supabase):** If the backend uses a key that is subject to Row Level Security, there must be a policy that allows **INSERT** and **SELECT** for the authenticated user on `v2_warm_up_tasks` (e.g. `user_id = auth.uid()`). Otherwise the insert is denied or the select returns no rows.

**Check:** Backend logs after reproducing the issue; run the migrations for `v2_warm_up_tasks`; in Supabase check Table Editor → `v2_warm_up_tasks` and Policies.

### B. Session not in `warm_up` (GET warm-up-task only)

**GET /session/{id}/warm-up-task** requires the session **status** to be exactly `warm_up`. If the session is `task_block`, `final_task_ready`, etc., the backend returns **404** `SESSION_NOT_FOUND` ("Session not found or not in warm_up").

**Check:** In Network tab, confirm the request to `/warm-up-task` and the response body. If it’s 404 with that message, the session status in the DB is not `warm_up` for that session id.

### C. Session or user mismatch

If the session belongs to another user, or the session id in the URL is wrong, **GET /session/{id}/warm-up-task** returns **404** (session not found). **POST /session/start** uses `request.user_id`; if auth is wrong, the wrong user is used.

**Check:** Confirm the frontend sends the correct `session_id` and that the backend auth provides the correct user.

### D. 500 V2_ERROR

Any unhandled exception in the warm-up path (e.g. in `v2_get_assigned_warm_up_task` or `select_warm_up_task`) returns **500** with `code: "V2_ERROR"`. The response body and backend logs will contain the exception message.

**Check:** Backend logs and the JSON body of the failing request.

---

## 3. Quick checklist

| Check | Action |
|-------|--------|
| Network tab | See which request fails: `/session/start` or `/warm-up-task`, and the status code + body. |
| Backend logs | Look for `v2_ensure_default_warm_up_task insert failed` or a Python traceback. |
| DB columns | `v2_warm_up_tasks` has `user_id`, `text`, `order_index`, `max_performance_score`. |
| RLS | Supabase: Table → `v2_warm_up_tasks` → Policies: allow SELECT/INSERT for the user. |
| Session status | For GET warm-up-task, session must be in status `warm_up`. |

---

## 4. Frontend

- If the UI only shows the session from **GET /status** and never calls **GET /warm-up-task** or **POST /session/start**, it may be relying on `session.warm_up_task_text`. That is only set after start (or after we snapshot on resume). So either call **POST /session/start** (or **GET /warm-up-task**) so the backend returns the task, or ensure the session row already has `warm_up_task_id` and `warm_up_task_text` from a previous start.
