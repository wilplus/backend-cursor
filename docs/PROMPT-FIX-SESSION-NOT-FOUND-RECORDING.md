# Prompt: Fix SESSION_NOT_FOUND / “Session must be in warm_up” (real architecture)

Use this prompt for another LLM or a frontend dev to fix the homework recording flow. **Use only the real backend:** `v2_sessions` table and homework endpoints (`/v2/homework/session/start`, `/status`, etc.). Do **not** refer to `api/sessions/[sessionId].ts`, `/api/sessions/:id/status`, or a `sessions` table with `state`. Do **not** let the frontend “create” DB rows or “force warm_up”—session creation and state transitions happen via the existing homework endpoints only.

---

## Goal

Fix failures for:

1. **POST /api/homework/session/:id/recording-upload-url**
2. **POST /api/homework/session/:id/recording-metrics-chunk** (and optionally GET if used)

When either returns `SESSION_NOT_FOUND` or `INVALID_SESSION_STATE`, ensure a valid session in **warm_up** before recording-1 using **real endpoints + DB**.

---

## What the two failing URLs mean

If either returns an error, one of these is true:

### A) The session id does not exist in `v2_sessions` (or it exists for a different user)

Frontend is using a wrong/stale session_id or wrong environment.

### B) The BFF is calling Flask without the student JWT

Backend resolves `user_id` from the token. If the BFF doesn’t forward `Authorization: Bearer <student_access_token>`, Flask may treat the user as unknown and session lookup fails (not found for that user).

### C) The session exists but `status != warm_up`

Backend rejects recording-1–related endpoints. The UI is showing the warm-up recording step but the session has already moved to **task_block** (or later). Backend returns **INVALID_SESSION_STATE** (or previously SESSION_NOT_FOUND) so the session “exists but wrong state” is distinguishable from “no session”.

---

## Two definitive DB checks (do these first)

In **Supabase SQL editor** run:

```sql
-- 1) Does this session exist at all?
select id, user_id, status, created_at
from public.v2_sessions
where id = '7bc8721f-7b76-442d-a7d2-cf78dedb61e9';
```

- **0 rows** → frontend is using a session_id that was never created, or stale, or wrong environment.
- **1 row** → note `user_id` and `status`.

Then:

```sql
-- 2) What are the latest sessions for this user?
select id, status, created_at
from public.v2_sessions
where user_id = '<THIS_STUDENT_UUID>'
order by created_at desc
limit 5;
```

If the session in the URL is not in this list, the frontend is likely holding the wrong id.

---

## Refined fix steps (for LLM/dev)

### 1) Gather facts (don’t guess)

For each failing request, from DevTools → Network capture:

- Full **Request URL**
- **HTTP status**
- **Response body** (JSON)
- **Response headers** → `server` (Next/Vercel vs Flask/Railway)

Confirm whether the response is from the Next BFF or from Flask.

### 2) Verify session exists and belongs to the user (Supabase)

Run:

```sql
select id, user_id, status from public.v2_sessions where id = '<session_id>';
```

- **Missing** → frontend is using wrong/stale session_id.
- **Present but wrong user_id** → auth/session mismatch (e.g. BFF not forwarding student JWT).
- **Present but status != 'warm_up'** → backend state machine vs UI step mismatch; show the step that matches `status`.

### 3) Session creation flow (frontend only — no DB writes from frontend)

Find where the frontend gets `session_id`. It **must** come from:

- **POST /api/homework/session/start**, or  
- **GET /api/homework/session/status**

(Both are BFF routes that proxy to Flask; Flask uses **v2_sessions** and homework endpoints only.)

- Do **not** call recording-upload-url or recording-metrics-chunk until the frontend has a valid `session_id` from one of these.
- Common bug: key mismatch — backend returns `session_id` or `session.id`; frontend must use e.g. `data.session_id ?? data.session?.id` and use it consistently.

**Fix:** On entering the homework flow:

1. Call **start** or **status**.
2. Set canonical id: `sessionId = data.session_id ?? data.session?.id`.
3. Only then call recording-upload-url / recording-metrics-chunk.

### 4) BFF must forward student auth to Flask

Inspect the Next.js BFF handlers for:

- `app/api/homework/session/[sessionId]/recording-upload-url/route.ts`
- `app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts`

They must send **`Authorization: Bearer <student_access_token>`** when proxying to Flask. If this header is missing, Flask may not resolve `user_id` and session lookup fails.

### 5) Backend error codes (already implemented)

- **SESSION_NOT_FOUND** (404) → session does not exist for that id/user.
- **INVALID_SESSION_STATE** (409) → session exists but status is not allowed for this endpoint (e.g. not `warm_up` for recording-1/upload-url). Use this to distinguish “wrong state” from “no session” when debugging.

### 6) Derive step from status (frontend)

After **GET session/status**, derive the current step from `session.status`:

- **warm_up** → show warm-up recording; allow recording-upload-url and recording-1.
- **task_block** → show metrics step (3 questions); do **not** show recording screen or call recording-upload-url for "1".
- **final_task_ready** → show final task + recording-2.
- **post_questions** → show post-questions.
- **completed** → show completed/report.

Do **not** assume “dashboard = step 1 = recording” without checking status. Do **not** reset or “force” session state from the frontend; state changes only via backend homework endpoints.

---

## Acceptance criteria

- With a valid active session in **warm_up**, both recording-upload-url and recording-metrics-chunk return **200**.
- No “Homework flow is not available yet” banner during normal warm-up recording.
- If session exists but status is not warm_up, backend returns **INVALID_SESSION_STATE** (not SESSION_NOT_FOUND) so the frontend can refetch status and show the correct step.

---

## What to paste to pinpoint the exact fix

From one failing request (e.g. recording-upload-url) in DevTools → Network, paste:

- **Status code**
- **Response JSON**
- **Response header `server`** (Next.js/Vercel vs Flask/Railway)

And run the first SQL query (`select ... from v2_sessions where id = '...'`) and paste the row (or “0 rows”). That tells us immediately: wrong session_id vs BFF not forwarding auth vs wrong session.status.

---

## Are you supposed to “upload SQL” or change frontend?

**No SQL upload for this error.** This is not a schema problem; it’s **session id / auth / state machine**. Frontend (and BFF) changes: ensure `session_id` comes from **start** or **status**, and that the BFF forwards the student JWT to Flask. Use the two SQL queries only to **verify** whether the session exists and what its status is.
