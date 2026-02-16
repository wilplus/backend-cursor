# Backend: session expiry (homework flow)

**Status: in-app expiry by age is disabled.** The app no longer deletes incomplete sessions just because they are older than 1 hour. The frontend still handles "session gone" (404 or no active session → user can start from scratch).

---

## Current behaviour

- **In-app:** **GET `/v2/homework/session/status`** and **POST `/v2/homework/session/start`** do **not** delete sessions by age. `v2_session_expired()` always returns `False`, so the active session is never removed for being old. Incomplete sessions persist until the user abandons them or completes the flow.
- **Optional script:** `run_cleanup_v2_sessions.py` can still be run (e.g. via cron) to delete incomplete sessions older than N hours. If you do not run it, no sessions are deleted by age.
- **SQL:** `migrations/cleanup_unused_sessions.sql` is a one-off script; it does not run automatically.

---

## How "no active session" is signaled

When there is no active session (user never started, or abandoned, or completed):

- **GET `/v2/homework/session/status`** returns **200** with  
  `{ "session": null, "has_active_session": false }`  
  (not 404).

The frontend already treats both:

- **404** (e.g. from abandon or session-scoped endpoints when the session is gone), and  
- **200** with no active session (`has_active_session: false` or no `session_id`)

as "no session" and lets the user start from scratch.

---

## Note: age vs inactivity

If you later re-enable expiry by age, it would be based on **session age** (e.g. 1h since `created_at`), not "1h since last activity". For true inactivity-based expiry, the backend would need something like `updated_at` or `last_activity_at` on `v2_sessions`, updated on each step (recording-1, metric-answers, recording-2, etc.), and `v2_session_expired()` would use that timestamp instead of `created_at`.
