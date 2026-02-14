# Frontend: Handle session not found / cleaned up (homework flow)

The backend cleans up incomplete v2_sessions older than 1 hour. When a session no longer exists, the frontend should avoid showing errors and instead redirect the user to step 0 (start) so they can start a new session.

Implement the following in the frontend.

---

## 1. Abandon session when session is not found (404)

**Backend behavior:**  
`POST /v2/homework/session/:sessionId/abandon` returns **404** with body  
`{ "code": "SESSION_NOT_FOUND", "error": "Session not found" }` when the session does not exist (e.g. already deleted by cleanup).

**Frontend should:**

- In the homework API client (e.g. `abandonSession(sessionId)`):
  - When the response status is **404**, do **not** throw. Treat it as success.
  - Return something like `{ abandoned: true, message: "Session not found or already cleared." }` so callers run the same success path as 200/409.

- In the homework flow component (e.g. `handleAbandon`):
  - On success (including when abandon returned 404), clear all session-related state and **redirect the user to step 0** (start screen).
  - Optionally show a different toast when the session was already gone, e.g.  
    *"Session was already cleared. You can start a new session."*  
    instead of *"Session abandoned. You can start a new session."*

**Result:** If the user clicks "Abandon session" and the session was already removed (e.g. by the 1-hour cleanup), they are not shown an error; they are sent to step 0 and can start a new session.

---

## 2. Refresh status when there is no active session

**Backend behavior:**  
`GET /v2/homework/session/status` returns **200** with  
`{ "session": null, "has_active_session": false }` when the user has no active session (e.g. session was cleaned up).

**Frontend should:**

- In the "Refresh" handler that refetches session status (e.g. when the user sees "Session status could not be determined. Please refresh."):
  - After calling GET session/status, if the response has **no active session**  
    (`has_active_session === false` or missing `session_id` / `session.id`):
    - Do **not** only show an error like "Could not load session."
    - **Reset to step 0:** clear `sessionId`, step, warm-up/task/question/report state, and any related sessionStorage keys (e.g. `homeworkReport`, `homeworkJustFinishedRecording2`).
    - Show a short success message, e.g.  
      *"Session was cleared. You can start a new one."*

**Result:** If the user clicks "Refresh" and their session was already cleaned up, they are taken to step 0 and can start a new session instead of staying on an error state.

---

## Summary

| Action   | When session is missing / cleaned up | Frontend behavior |
|----------|--------------------------------------|-------------------|
| Abandon  | API returns 404                      | Treat as success; clear state; **redirect to step 0**; optional toast "Session was already cleared." |
| Refresh  | GET status returns no active session | Clear state; **redirect to step 0**; toast "Session was cleared. You can start a new one." |

No backend API changes are required for this; the backend already returns 404 for abandon and `has_active_session: false` for status when the session does not exist.
