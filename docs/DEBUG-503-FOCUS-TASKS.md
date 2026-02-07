# 503 when saving focus task – how to find the real reason

If you see **503** and "Failed to create focus task. Run migrations/v2_focus_tasks.sql if not done", the backend is returning the **real error** in the response body. Use it to fix the issue.

---

## 1. Get the real error from the browser

1. Open **DevTools** (e.g. right‑click → Inspect → **Network** tab).
2. Click **Save** again in the "Add focus task" modal.
3. In Network, click the red request to **focus-tasks** (method POST).
4. Open the **Response** (or **Preview**) tab.
5. You should see JSON like:
   ```json
   {
     "error": "Failed to create focus task...",
     "detail": "the actual error from the database or server",
     "message": "Failed to create... Server said: the actual error..."
   }
   ```
6. **Copy the `detail` or `message` value** – that is the real reason the save failed.

---

## 2. Typical causes and what to do

| What you see in `detail` / `message` | What it usually means | What to do |
|--------------------------------------|------------------------|------------|
| `relation "v2_focus_tasks" does not exist` or `42P01` | Table not in the DB the backend uses | Run **migrations/v2_focus_tasks.sql** in the **same** Supabase project the backend uses (check `SUPABASE_URL` / env in the backend). |
| `permission denied`, `policy`, `RLS` | Row Level Security blocking insert | In Supabase: Table Editor → `v2_focus_tasks` → RLS. Either add a policy that allows the backend (e.g. service role) to insert, or disable RLS for this table if the backend uses the service role key. |
| `violates foreign key constraint` or `user_id` | `user_id` is not in `auth.users` | The student ID in the URL must exist in `auth.users`. Check that the admin is using a real user ID from your app. |
| `null value in column "user_id"` | Backend sent empty user_id | Bug in backend or BFF: ensure the request uses the correct student `user_id` in the URL and/or body. |

---

## 3. Confirm the backend is using the right DB

- Backend uses **Supabase** via `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (or similar) in its environment.
- The migration must be run in **that** Supabase project (same URL).
- In Supabase SQL Editor for that project, run:
  ```sql
  SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_focus_tasks');
  ```
  If you get `false`, the table is missing in that project – run **migrations/v2_focus_tasks.sql** there.

---

## 4. Show the real error in the UI (frontend)

So the user sees the server message instead of only the generic one:

- On **503**, read the response JSON and show **`detail`** or **`message`** in the toast (e.g. `response.detail || response.message || response.error`).
- That way the next time something fails, the toast will show e.g. "relation v2_focus_tasks does not exist" or "permission denied for table v2_focus_tasks".

---

## 5. Verify backend from the command line

**GET focus-tasks (expect 200 and JSON with `focus_tasks` array):**

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  "https://your-backend/v2/admin/students/SOME_USER_ID/focus-tasks"
```

Replace `YOUR_ADMIN_TOKEN`, `https://your-backend`, and `SOME_USER_ID` with real values. You should get **200**. To see the body: drop `-s -o /dev/null -w "%{http_code}"` and run:

```bash
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  "https://your-backend/v2/admin/students/SOME_USER_ID/focus-tasks"
```

---

## 6. Verification checklist

| Check | What to verify |
|-------|----------------|
| **Backend URL** | `BACKEND_URL` (or whatever your BFF uses) points to the real backend. Wrong host or port → request never hits the right server. |
| **Path** | Backend route is exactly `/v2/admin/students/:id/focus-tasks` (and same for pool). Extra slash or typo → 404. |
| **Auth** | BFF sends a valid admin token; backend returns 401/403 if not. Toast will show “Unauthorized” or the backend’s message. |
| **Response shape** | Backend returns JSON with a `focus_tasks` array (or the BFF normalizes it). If it returns 200 with HTML or a different JSON shape, the BFF should still normalize to `focus_tasks: []` on GET; POST/PUT/DELETE could fail or show a confusing error. |
| **Network** | From the machine running the BFF, `curl -H "Authorization: Bearer <token>" "<BACKEND_URL>/v2/admin/students/<id>/focus-tasks"` returns 200 and JSON. If this fails, the BFF can return 502 with “Backend unreachable” instead of 500. |
