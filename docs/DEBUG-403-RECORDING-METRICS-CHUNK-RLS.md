# Debug: 403 on recording-metrics-chunk — "new row violates row-level security policy"

When the **recording-metrics-chunk** request returns **403 Forbidden** with:

- **"Unauthorized"**
- **"new row violates row-level security policy"**

the failure is almost certainly **not** from the Flask homework route for recording-metrics-chunk.

---

## What the Flask backend does (recording-metrics-chunk)

- **GET** session via `db.v2_get_session(session_id, user_id)` (Supabase **SELECT** only).
- **In-memory** processing via `process_pcm_chunk(...)` (no DB write).
- Returns **200** with `{ seq, t_ms, voiced_ratio, pause_score }`.

The backend uses the **Supabase service role key** for all DB access, so it **bypasses RLS**. It does **not** insert or update any row in this handler, and it does **not** return 403 or an RLS error message. So the **403 with "new row violates row-level security policy"** is coming from somewhere else in the chain.

---

## Where the bug is likely coming from

### 1. BFF (Next.js) writing to Supabase

The BFF route that handles **POST /api/homework/session/[sessionId]/recording-metrics-chunk** might:

- Proxy the request to Flask (which returns 200), **and**
- Do an **extra** step: e.g. write chunk data or metrics to a Supabase table (Postgres or Realtime).

If that write uses the **Supabase client with the anon key** (and the user’s JWT), the insert runs in the **user’s** security context. If the table has **RLS** that only allows inserts when e.g. `user_id = auth.uid()` and the row has a different `user_id`, or `user_id` is null, Supabase returns **403** with **"new row violates row-level security policy"**. The BFF then returns that 403 to the browser.

**What to do:** In the BFF handler for recording-metrics-chunk, check whether it performs any **insert** (or update) to Supabase. If yes, either:

- Remove that write for this endpoint (if chunks are only for real-time UI and don’t need to be stored), or  
- Ensure the inserted row has the correct **user_id** (from the JWT) and that the table’s RLS policy allows that insert, or  
- Use the **service role** for that write (server-side only, no user context) and ensure the row has the correct user_id from the request/session.

### 2. BFF not proxying to Flask / wrong response path

Less likely, but possible: the BFF does **not** call Flask and instead tries to handle the request by writing to Supabase directly. That write then fails with RLS as above.

**What to do:** Ensure the BFF **proxies** the request to **POST {BACKEND}/v2/homework/session/:id/recording-metrics-chunk** with the same body and **Authorization** header, and returns the backend response. No extra Supabase insert in this path unless you intentionally persist chunks and have fixed RLS.

### 3. Frontend calling Supabase directly

If the frontend sends the same PCM data to **Supabase** (e.g. Realtime or a PostgREST endpoint) in addition to the BFF, that Supabase call could fail with 403 RLS. The Network tab would show a request to a Supabase URL, not (only) to `/api/homework/.../recording-metrics-chunk`.

**What to do:** Check whether the UI sends any request to a Supabase host for metrics/chunks. If yes, fix RLS for that table or remove the direct Supabase write and rely on the BFF → Flask flow only.

---

## Summary

| Observation | Likely cause |
|-------------|--------------|
| 403 + "new row violates row-level security policy" on recording-metrics-chunk | A **write** to Supabase (insert/update) is failing RLS. The Flask handler does **not** write; so the write is in the **BFF** (or a direct frontend → Supabase call). |
| Fix | Find where that insert happens (BFF or frontend). Either stop writing for this flow, or set the row’s **user_id** correctly and align RLS policies so the inserting role (anon + JWT user, or service role) is allowed to insert. |

No backend (Flask) change is required for this 403; the fix is in the BFF or in Supabase RLS for the table being written to.
