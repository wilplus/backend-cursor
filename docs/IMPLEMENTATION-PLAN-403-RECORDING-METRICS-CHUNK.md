# Implementation plan: Fix 403 on recording-metrics-chunk (RLS)

Goal: remove or fix the Supabase write that triggers **403** and **"new row violates row-level security policy"** when the frontend calls the recording-metrics-chunk endpoint. The Flask backend does not perform this write; the fix is in the **BFF** and/or **frontend** and optionally **Supabase RLS**.

---

## Phase 1: Locate the failing write (BFF / frontend)

| Step | Action | Owner | Done |
|------|--------|-------|------|
| 1.1 | **Confirm who returns 403.** In DevTools → Network → failed `recording-metrics-chunk` request: check **Request URL** (BFF path vs Supabase host) and **Response headers** (e.g. `server`, `x-request-id`). If URL is `/api/homework/.../recording-metrics-chunk` → response is from BFF (or what BFF proxies to). If URL is `*.supabase.co/...` → direct Supabase call. | Frontend/BFF | ☐ |
| 1.2 | **BFF: find the recording-metrics-chunk handler.** In the Next.js (or BFF) repo, search for the route that handles `POST .../recording-metrics-chunk` (e.g. `api/homework/session/[sessionId]/recording-metrics-chunk` or similar). | BFF | ☐ |
| 1.3 | **Inspect handler body.** In that handler, list every Supabase/Postgres call: `insert`, `upsert`, `update`, Realtime publish, Storage upload. If there is any write (especially insert) that runs when this endpoint is called, that write is the prime candidate for the RLS failure. | BFF | ☐ |
| 1.4 | **Frontend: check for extra Supabase calls.** In the frontend, find where the app sends PCM/metrics (e.g. `recording-metrics-chunk` fetch). Check if it also calls Supabase (e.g. `supabase.from('...').insert(...)` or Realtime) in the same flow. If yes, note the table and payload. | Frontend | ☐ |

**Outcome:** You know whether the failing write is in the **BFF** handler, in a **direct frontend → Supabase** call, or both. You know the **table** (and operation) that triggers the RLS error.

---

## Phase 2: Fix the write (choose one strategy)

### Option A: Remove the write (if chunks are only for real-time UI)

If metrics chunks are **not** required to be persisted (only used for the dartboard/real-time UI and Flask already returns the computed metrics):

| Step | Action | Owner | Done |
|------|--------|-------|------|
| 2A.1 | In the BFF handler: remove any Supabase insert/upsert/update (and any Realtime publish) for this endpoint. Keep only: forward request to Flask with `Authorization` and body, return Flask response. | BFF | ☐ |
| 2A.2 | In the frontend: remove any direct Supabase insert/update for metrics chunks in this flow. Keep only the call to the BFF (which proxies to Flask). | Frontend | ☐ |

**Outcome:** No Supabase write in this path → no RLS error → 403 goes away.

---

### Option B: Keep the write and fix RLS / payload

If you **do** need to persist chunk metrics (e.g. for analytics or replay):

| Step | Action | Owner | Done |
|------|--------|-------|------|
| 2B.1 | **Row payload:** Ensure every inserted/updated row includes the correct **user_id** (and **session_id** if the table has it). In BFF: take `user_id` from the validated JWT (or session). In frontend: do not insert from the client unless the table RLS allows it and the row has `user_id` matching `auth.uid()`. | BFF / Frontend | ☐ |
| 2B.2 | **RLS policy:** In Supabase, open the table that receives the insert. Check RLS policies for **INSERT**. Add or adjust a policy so that: either (a) `user_id = auth.uid()` for the inserted row and the policy allows `INSERT` when that holds, or (b) the insert is done with the **service role** (BFF server-side only) and the row has the correct `user_id`; then RLS may not apply if using service role. | Supabase / BFF | ☐ |
| 2B.3 | **BFF auth:** If the BFF uses the **anon** key + user JWT for this insert, the insert runs as that user; the row must satisfy RLS (e.g. `user_id = auth.uid()`). If the BFF uses the **service role** for the insert, ensure the request body or session provides `user_id` and the BFF sets it on the row. | BFF | ☐ |

**Outcome:** The write succeeds; 403 and RLS error disappear.

---

## Phase 3: Ensure BFF → Flask proxy is correct (always)

Regardless of Option A or B:

| Step | Action | Owner | Done |
|------|--------|-------|------|
| 3.1 | BFF handler must **proxy** `POST {BACKEND}/v2/homework/session/:id/recording-metrics-chunk` with: same method, body (e.g. JSON with `seq`, `t_ms`, `pcm_base64` or equivalent), and **Authorization: Bearer &lt;student_access_token&gt;**. Return the backend status and body to the client. | BFF | ☐ |
| 3.2 | Smoke test: with a session in `final_task_ready`, open the Final task step, start the dartboard/metrics flow. Confirm **recording-metrics-chunk** returns **200** (and no 403). Check Network tab and backend logs if needed. | QA / Dev | ☐ |

---

## Checklist summary

- [ ] Phase 1: Identified whether 403 is from BFF or direct Supabase; found the handler and the exact write (table + operation).
- [ ] Phase 2: Either removed the write (Option A) or fixed row payload + RLS (Option B).
- [ ] Phase 3: BFF proxies to Flask with auth; recording-metrics-chunk returns 200 in the Final task step.

**No changes are required in the Flask backend** for this fix; the backend already only reads the session and returns in-memory metrics.
