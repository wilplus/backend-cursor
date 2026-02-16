# Debug: Does GET status return a session that exists in the DB?

When `GET /v2/homework/session/status` returns a `session_id` but later `POST metric-answers` (or abandon) returns **404 SESSION_NOT_FOUND**, and `SELECT * FROM v2_sessions WHERE id = '...'` returns **0 rows**, the only two possibilities are:

1. **Status is not reading from `v2_sessions`** (cache, wrong DB, etc.) → status would be broken.
2. **The row existed when status ran but was deleted afterward** (expiry, abandon, cleanup cron, or frontend using a stale session_id).

This guide walks you through the test that decides which it is.

---

## How status works (for context)

- **Status handler** (`routes/homework.py`): calls `db.v2_get_active_homework_session(user_id)` → direct **SELECT** from `v2_sessions` (no cache, no Redis).
- **Expiry:** If that session is incomplete and older than **1 hour** (`created_at`), status **deletes** it and returns **no session** (`has_active_session: false`). So when status **returns** a session, it did **not** delete it in that request.
- **Deletion elsewhere:** The row can still be deleted by: another tab/window calling status or start (session became >1h), user clicking Abandon, or `run_cleanup_v2_sessions.py` (cron).

---

## Step 1: Add / confirm logging

The backend now logs when it returns a session:

```text
STATUS returning session_id: <uuid> (run SQL for this id right after status to confirm row exists)
```

- **Where:** `routes/homework.py` in the GET status handler, right before building the JSON response.
- **Where it appears:** App logs (e.g. Railway logs, or terminal if you run `python app.py` locally). Search for `STATUS returning session_id`.

---

## Step 2: Run the test (same Supabase project as backend)

Do this in order, with **as little delay as possible** between (2a) and (2b).

### 2a. Call GET status (with a session that exists)

- **With an active session:** Open the homework app, ensure you have an active session (e.g. you see warm-up or metric questions step). Then call:

  ```bash
  curl -s -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
    "https://YOUR_BACKEND_URL/v2/homework/session/status"
  ```

  Or trigger the same request from the frontend (e.g. refresh the homework page so it calls status).

- From the **JSON response**, note `session_id` (or `session.id`).  
  Or from **backend logs**, note the id in the line: `STATUS returning session_id: <uuid>`.

### 2b. Immediately query the DB

Within **seconds**, in the **same** Supabase project (Dashboard → SQL Editor), run:

```sql
SELECT id, user_id, status, created_at
FROM v2_sessions
WHERE id = 'PASTE_THE_SESSION_ID_HERE';
```

Replace `PASTE_THE_SESSION_ID_HERE` with the exact UUID from step (2a).

---

## Step 3: Interpret the result

| SQL result | Conclusion |
|------------|------------|
| **0 rows** | At the time you ran the query, the row did **not** exist. So either: (A) Status is **not** reading from `v2_sessions` (bug in status/DB), or (B) Something **deleted** the row in the few seconds between status returning and you running the SQL (e.g. another request, or cron). If you were very fast (< 2–3 s), (A) is more likely. |
| **1 row** | The row **exists** when status returns. So status **is** reading from the DB correctly. The 404 you saw earlier was because the session was deleted **after** that moment (e.g. 1h expiry, abandon, or cleanup), or the frontend used a **stale** session_id from an old session. |

---

## If 0 rows (status might not be reading from DB)

- Confirm the backend’s `SUPABASE_URL` (and env) is the same project where you ran the SQL.
- Search the codebase for any caching of “active session” (e.g. Redis, global dict) used by the status route. Current code uses only `db.v2_get_active_homework_session(user_id)` → Supabase `v2_sessions`; there is no cache in the repo.
- If you truly have no cache and same DB: re-run the test; if it’s 0 rows again with minimal delay, consider adding a **second** query inside the status handler right before `return jsonify(...)` that does `SELECT id FROM v2_sessions WHERE id = :id` and logs whether the row exists. That confirms whether the row exists at the exact moment status is about to return.

---

## If 1 row (row exists when status returns)

Then the bug is **session lifecycle / staleness**, not “status not reading from DB”:

- **1h expiry:** Incomplete sessions are deleted when older than 1 hour. If the user left the metric step open for >1h, a later status/start or cleanup could delete the session; the next metric-answers would 404. Fix: frontend treats 404 as “session gone”, refetches status, and shows start/step 0 (see `docs/FRONTEND-SESSION-NOT-FOUND.md`). Optionally extend or change expiry (e.g. `updated_at`-based) if you want longer-lived incomplete sessions.
- **Stale session_id:** Frontend might be reusing an old `session_id` from a previous session (e.g. from an earlier status response). Ensure the UI always uses the `session_id` from the **latest** status (or from the last successful step response), and refetches status after errors.
- **Abandon / cleanup:** User or another tab called abandon, or `run_cleanup_v2_sessions.py` ran. Same as above: treat 404 as session gone and refetch status.

---

## Quick checklist

- [ ] Backend logs show: `STATUS returning session_id: <uuid>` when status returns a session.
- [ ] You called GET status and noted the exact `session_id`.
- [ ] You ran `SELECT ... FROM v2_sessions WHERE id = '...'` in the **same** Supabase project within seconds.
- [ ] You recorded: 0 rows vs 1 row and used the table above to decide next steps.

This single test tells you whether the problem is “status not using DB” or “row deleted / stale id after status.”
