# Frontend: Session gone → start over (never block the user)

This doc lives in the **backend** repo so both teams have a single reference. The behavior described below is implemented in the **frontend** (homework flow).

---

## Principle

> If anything about the current session is broken, expired, or missing, don’t trap the user—reset and let them start again.

When the backend returns “session not found” (404) or the user has no active session, the frontend should **never** show a dead-end error. It should clear local state, go to **step 0**, and show a short message so the user can start a new lesson immediately.

---

## What the frontend implements

### 1. Homework API client (`homework-client.ts`)

- On **404** responses, the thrown error includes:
  - **`code`** from the backend body (e.g. `"SESSION_NOT_FOUND"`).
  - **`status: 404`** so the UI can detect “session gone” without relying only on the message.
- **Abandon** already treats 404 as success (no throw); callers run the same “clear and go to step 0” path.

### 2. Single “start over” helper (`HomeworkFlowCard.tsx`)

- **`startOverFromScratch()`**  
  Local-only reset: abort ref, clear all homework refs, clear `sessionStorage` (`homeworkReport`, `homeworkJustFinishedRecording2`), reset session id, step, warm-up/task/questions/report state, errors, loading. Sets **step to 0**. No API call. Use when the session is already gone (e.g. after a 404).

- **`isSessionGoneError(e)`**  
  Returns true when the error indicates the session is gone:
  - `e.code === "SESSION_NOT_FOUND"`, or
  - `e.status === 404`, or
  - message contains “session not found” or “no active session”.

### 3. Where “session gone” is handled

At the **top** of the catch block (before any other error handling), for:

- **Upload recording 1** (`handleRecording1Complete`)
- **Upload recording 2** (`handleRecording2Complete`)
- **Submit metric answers** (`handleMetricAnswersSubmit`)
- **Submit post answers** (`handlePostAnswersSubmit`)
- **Load report** (`getReport` in useEffect)

the logic is:

1. If **`isSessionGoneError(e)`**:
   - Toast: *“Your session is gone. You can start a new lesson.”*
   - Call **`startOverFromScratch()`**
   - **return**
2. Otherwise, run the existing error handling (e.g. INVALID_SESSION_STATE, RECORDING_1_PROCESSING, etc.).

### 4. Already in place (unchanged)

- **GET status** with no active session → clear state, step 0, friendly message (e.g. “Session was cleared. You can start a new one.”).
- **Abandon** (200 or 404) → clear state, step 0; optional different toast when 404 (“Session was already cleared.”).
- “Start new homework” / “Abandon session” buttons remain the explicit escape; the above ensures **any** 404 from a session-scoped call also leads to step 0.

---

## Backend behavior (no change required)

- **POST /session/start** – Never returns 4xx for “no session” or “expired session”; always resumes or creates a new session.
- **GET /session/status** – Returns `has_active_session: false`, `session: null` for no/expired session (200).
- **POST /session/:id/abandon** – 200 when deleted, 404 when already gone.
- **Other session-scoped routes** (recording-1, metric-answers, recording-2, post-answers, report) – Return **404** with `code: "SESSION_NOT_FOUND"` when the session does not exist. Frontend treats that as “session gone” and resets to step 0.

---

## Net result

- Expired, cleaned-up, or missing sessions never leave the user stuck.
- They always get a clear message and land on step 0, where they can start a new lesson.
- All of this is implemented in the **frontend** repo; this doc in the backend repo is for alignment and onboarding.
