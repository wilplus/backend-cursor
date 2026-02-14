# Backend: 1h session expiry (homework flow)

**Status: implemented.** No change required for the frontend; it already handles “session gone” (404 or no active session → user can start from scratch).

---

## What the backend does

- **Expiry rule:** Incomplete v2 homework sessions (status ≠ `completed`) are considered **expired** when older than **1 hour** (by `created_at`).
- **When expiry is applied:**
  - **GET `/v2/homework/session/status`** — If the user’s active session is expired, the backend **deletes** it and returns “no active session”.
  - **POST `/v2/homework/session/start`** — Same: if the current active session is expired, it is deleted and a new session is created.
- **Optional cron:** `run_cleanup_v2_sessions.py` can be run (e.g. every 15–60 min) to delete incomplete sessions older than 1h; expiry is also applied on-demand on status/start above.

---

## How “no active session” is signaled

When a session is expired or deleted:

- **GET `/v2/homework/session/status`** returns **200** with  
  `{ "session": null, "has_active_session": false }`  
  (not 404).

The frontend already treats both:

- **404** (e.g. from abandon or session-scoped endpoints when the session is gone), and  
- **200** with no active session (`has_active_session: false` or no `session_id`)

as “no session” and lets the user start from scratch.

---

## Note: age vs inactivity

Expiry is currently based on **session age** (1h since `created_at`), not “1h since last activity”. If you later want true inactivity (e.g. reset the 1h timer on each step), the backend would need something like `updated_at` or `last_activity_at` on `v2_sessions`, updated on each step (recording-1, metric-answers, recording-2, etc.), and `v2_session_expired()` would use that timestamp instead of `created_at`.
