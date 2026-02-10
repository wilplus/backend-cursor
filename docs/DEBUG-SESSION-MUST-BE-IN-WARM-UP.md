# Debug: "Session must be in warm_up for recording-1"

When the user is on the **recording page** (warm-up step with dartboard) but the app shows:

- **"Homework flow is not available yet"**
- API response: `{ "code": "SESSION_NOT_FOUND", "error": "Session must be in warm_up for recording-1" }`

the request that failed is almost certainly **POST .../recording-upload-url** (with `{ "recording": "1" }`) or **POST .../recording-1**. Both require the session **status** to be **`warm_up`**. If it isn’t, the backend returns that error.

---

## What it means

The **session exists** but its **status** in the DB is **not** `warm_up`. So the backend correctly rejects “give me an upload URL for recording-1” or “submit recording-1” because the session has already moved on (or was never in warm_up).

Typical causes:

1. **Session already progressed**  
   The user (or another tab) already completed recording-1. The session is now **task_block** (or later). The UI still shows the **warm-up recording** step instead of the **metrics** step (3 questions). So when the user tries to “start recording” again, the frontend calls recording-upload-url or recording-1, and the backend returns “Session must be in warm_up”.

2. **Stale or wrong step on the client**  
   The frontend is not deriving the current step from **GET session/status**. It might be using an old cached status, or a default “step 1 = recording”, so it shows the recording screen even when `session.status === "task_block"`.

3. **Session created/updated with wrong status**  
   Less common: the session was created or updated with a status other than `warm_up` (e.g. manual DB change, or a bug elsewhere).

---

## How to confirm

1. **Which request fails**  
   In DevTools → Network, find the request whose response body is  
   `{ "code": "SESSION_NOT_FOUND", "error": "Session must be in warm_up for recording-1" }`.  
   It will be either:
   - **POST .../recording-upload-url**, or  
   - **POST .../recording-1**

2. **What the session status actually is**  
   Call **GET /v2/homework/session/status** (or your BFF equivalent) with the same auth and note the **session** object:
   - **`session.status`** — if it’s **task_block**, **final_task_ready**, **post_questions**, or **completed**, the backend will never accept recording-upload-url for recording "1" or recording-1.
   - **`session.recording_1_id`** — if set, recording-1 was already completed for this session.

So: if `status !== "warm_up"` and/or `recording_1_id` is set, the backend is behaving as designed; the issue is that the UI is still showing the warm-up recording step.

---

## What to do (fix)

### Frontend: derive step from GET session/status

- When loading the homework flow (dashboard or homework page), call **GET session/status** and derive the **current step** from the response:
  - **status === "warm_up"** → step 1: show **warm-up recording** (dartboard + “Start Recording”). Only then call recording-upload-url / recording-1.
  - **status === "task_block"** → step 2: show the **three metric questions** (no recording screen).
  - **status === "final_task_ready"** → step 3: show **final task** and recording-2.
  - **status === "post_questions"** → step 4: show **post-questions**.
  - **status === "completed"** → step 5 / completed.

- Do **not** assume “dashboard = step 1 = recording” without checking **session.status**. If you cache status, invalidate it when the user returns to the homework flow or when a request fails with SESSION_NOT_FOUND.

- If **session.status === "task_block"** but the UI was showing the recording step, **navigate or re-render to the metrics step** (show the 3 questions). Then the user can continue the flow without hitting “Session must be in warm_up” again.

### Optional: show a clearer message

- When the backend returns **SESSION_NOT_FOUND** with “Session must be in warm_up for recording-1”, you can show a message like:  
  “Your session has already moved to the next step. Taking you to the right step…” and then refetch **GET session/status** and show the step that matches **status** (e.g. metrics if task_block).

### Backend

- No change required for this error. The backend is enforcing that recording-1 (and recording-upload-url for "1") only run when the session is in **warm_up**. The fix is to have the frontend show the correct step from **session.status**.

---

## Summary

| Observation | Meaning |
|-------------|--------|
| Error “Session must be in warm_up for recording-1” | Session status is not `warm_up` (likely already **task_block** or later). |
| User sees recording screen but error on upload-url / recording-1 | UI is showing step 1 (recording) even though session is past that step. |
| Fix | Derive step from **GET session/status** and show **metrics** (step 2) when **status === "task_block"**; only show recording when **status === "warm_up"**. |
