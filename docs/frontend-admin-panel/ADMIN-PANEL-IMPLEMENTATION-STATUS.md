# Admin panel: what I can see, what’s implemented, and why you get 404

**No "Tasks" tab.** Admin has only the **Students** tab. There is no focus-tasks UI; tasks exist only in the DB. **/api/admin/tasks** must not be called if you have no task UI — but something in your frontend is still calling it (hence 404). See below how to find and remove that call.

## What I can see (backend repo only)

I only have access to the **backend-cursor** repo. I can see:

- **Backend (Flask):** routes, DB, auth — e.g. `routes/v2_routes.py`, `services/db.py`, `auth.py`.
- **Docs in the backend repo:** reference BFF routes under `docs/frontend-admin-panel/api-routes/`, reference admin client and pages under `docs/frontend-admin-panel/`, and `docs/APP-DESCRIPTION-FRONTEND.md`.

I **cannot** see your **frontend** repo (e.g. frontend-cursor). I do not know:

- Whether you have `src/app/api/admin/tasks/route.ts` or `src/app/api/v2/admin/tasks/route.ts`.
- Where your `getAuth` (or equivalent) lives.
- Whether you use the App Router or Pages Router, or a different folder layout.

So I can’t “see” your current admin panel implementation — only what the backend expects and what the docs say to build.

---

## Frontend: how to stop /api/admin/tasks from being called (fix 404)

The path **/api/admin/tasks** is not a page — it's an API. It gets called when **your code** runs `adminApi.getTasks()` or `fetch("/api/admin/tasks")`. There is no "tasks page"; you only have the Students page. So the call is coming from code that runs **when you're already on the Students flow** (e.g. when you open a student profile). The pathname doesn't need to change; you need to **remove the code that requests tasks**.

Do this in your **frontend** repo:

1. **Search for what triggers the request**  
   Search for: `getTasks`, `createTask`, `/api/admin/tasks`, or `"/tasks"`.  
   Typical place: the **student profile page** (e.g. `app/admin/students/[id]/page.tsx`).

2. **On the student profile page, remove the tasks request from the initial load**  
   Find the `load` / `useEffect` / `Promise.all` that runs when the profile mounts. You will see something like: `adminApi.getStudentProfile(id)`, `adminApi.getExercises()`, **`adminApi.getTasks()`**, `adminApi.getPostQuestions()`, `adminApi.getWarmUpTasks(id)`.  
   **Remove** `adminApi.getTasks()` from that list, and remove the handling for that result (e.g. `setTasks(...)` and the `tasksRes` / `tasks` state). Save; the profile will no longer request `/api/admin/tasks` when you open a student.

3. **Remove any "Select Focus Tasks" modal**  
   Remove the modal and the button that opens it, so no code path ever calls `getTasks()` or `createTask()`.

4. **Optional**  
   Remove `tasks` state and any UI that shows or selects tasks. You can omit `assigned_next_task_ids` from the save payload if you don't use it.

After this, no request goes to `/api/admin/tasks`, so the 404 stops. You stay on the Students pathname; only the **requests** made by the profile page change.

---

## What is implemented where

### 1. Backend (Flask) — implemented

| Thing | Status | Location |
|-------|--------|----------|
| GET /v2/admin/tasks | Implemented | `routes/v2_routes.py` |
| POST /v2/admin/tasks | Implemented | `routes/v2_routes.py` |
| PUT /v2/admin/tasks/:id | Implemented | `routes/v2_routes.py` |
| DELETE /v2/admin/tasks/:id | Implemented | `routes/v2_routes.py` |
| Admin auth (require_admin) | Implemented | `routes/admin.py` + v2_routes |
| v2_tasks table, v2_insert_task, etc. | Implemented | `services/db.py`, migrations |

The backend is ready. If you call **https://your-backend-url/v2/admin/tasks** with a valid admin Bearer token, you get 200 and `{ "tasks": [...] }`.

### 2. Reference / docs (in backend repo) — templates, not your app

These are **reference** implementations. They are not part of a running app; they are files you are supposed to **copy** into your frontend repo.

| Thing | In backend repo (docs) | Purpose |
|-------|------------------------|---------|
| BFF route for tasks | `docs/frontend-admin-panel/api-routes/tasks-route.ts` | Copy to **your** `src/app/api/admin/tasks/route.ts` |
| BFF route for tasks/:id | `docs/frontend-admin-panel/api-routes/tasks-[id]-route.ts` | Copy to **your** `src/app/api/admin/tasks/[id]/route.ts` |
| Admin API client | `docs/frontend-admin-panel/lib/api/admin-client.ts` | Reference for how URLs are built: **`/api/admin` + path** (e.g. `/api/admin/tasks`) |
| Admin health route | `docs/frontend-admin-panel/api-routes/health-route.ts` | Copy to **your** `src/app/api/admin/health/route.ts` to test that `/api/admin/*` works |
| Student profile page, etc. | `docs/frontend-admin-panel/app/admin/...` | Reference UI; you may have your own pages |

So: “what is implemented” in the admin panel **in the backend repo** is: backend API + reference BFF/client code. Nothing in `docs/frontend-admin-panel/` runs as your app until you copy it into the frontend repo.

### 3. Your frontend app — unknown from here

What is **actually** implemented in your frontend (e.g. frontend-cursor) I cannot see. For the 404 to go away, **your** app must have:

- A Next.js API route that handles **GET** and **POST** for the path **`/api/admin/tasks`**.
- In the App Router, that means a file at **`src/app/api/admin/tasks/route.ts`** (or the equivalent under your `app/` directory).

If that file is missing, or lives under a different path (e.g. `api/v2/admin/tasks`), Next.js will not handle `/api/admin/tasks` and the browser will get 404. The “more error communicate” we added only appears **if that route file runs**. If the route never runs (wrong path / missing file), you still get a plain 404 and no custom body or headers.

---

## Why you get 404 and why you don’t see extra errors

- **Why 404:** The request from the browser goes to **`/api/admin/tasks`**. In Next.js App Router, that URL is handled only if there is a **route handler** at **`app/api/admin/tasks/route.ts`** (relative to your app root). If that file doesn’t exist there (or the path is different), Next.js returns **404** and you don’t see any of our diagnostic JSON or headers, because our code never runs.
- **Why no “more error communicate”:** The diagnostic `_debug` and `X-BFF-Route` are returned **by the BFF route handler**. If that handler is never executed (route missing or wrong path), the response is just the default 404 (often HTML or empty). So you only see “more errors” when the correct BFF file is in place and actually invoked.

---

## What must exist in your frontend repo (checklist)

Run this **in your frontend repo** (e.g. frontend-cursor) to see what’s there. Adjust paths if you use `app/` in a different place (e.g. `src/app/` vs `app/`).

```bash
# 1) Are you using App Router? (app/api/...)
ls -la src/app/api/admin/ 2>/dev/null || ls -la app/api/admin/ 2>/dev/null || echo "No app/api/admin folder found"

# 2) Is the tasks route file present at the path that matches /api/admin/tasks?
ls -la src/app/api/admin/tasks/route.ts 2>/dev/null || ls -la app/api/admin/tasks/route.ts 2>/dev/null || echo "MISSING: api/admin/tasks/route.ts (this causes 404 for /api/admin/tasks)"

# 3) Did you put it under v2 by mistake?
ls -la src/app/api/v2/admin/tasks/route.ts 2>/dev/null || ls -la app/api/v2/admin/tasks/route.ts 2>/dev/null && echo "WARNING: route is under api/v2/admin/tasks -> URL is /api/v2/admin/tasks, but admin client calls /api/admin/tasks"

# 4) What does your admin client use as base URL?
grep -n "api/admin\|/api/" src/lib/api/admin-client.ts 2>/dev/null || grep -n "api/admin\|/api/" lib/api/admin-client.ts 2>/dev/null || true
```

Interpretation:

- If **“MISSING: api/admin/tasks/route.ts”** appears → create that file (copy from `docs/frontend-admin-panel/api-routes/tasks-route.ts` in the backend repo) and fix the `getAuth` import. Restart dev server.
- If **“WARNING: route is under api/v2/admin/tasks”** appears → move the file to **`api/admin/tasks/route.ts`** (so the URL is `/api/admin/tasks`, which is what the admin client calls).
- If **`api/admin`** doesn’t exist → create **`src/app/api/admin/`** (or `app/api/admin/`) and add **`tasks/route.ts`** and, for sanity check, **`health/route.ts`** (copy from `docs/.../api-routes/health-route.ts`).

---

## Summary

| Layer | Implemented? | Where |
|-------|--------------|--------|
| Backend (Flask) /v2/admin/tasks | Yes | backend-cursor (routes, db) |
| BFF route /api/admin/tasks | Only as **reference** in backend repo | You must add it in **your** frontend at `src/app/api/admin/tasks/route.ts` |
| Admin client calling /api/admin/tasks | Defined in **reference** admin-client | Your frontend must use the same URL pattern: `/api/admin` + path |
| Your actual frontend files | Unknown from here | Run the checklist above in your frontend repo |

The 404 will stop when your frontend has a route handler at the path that serves **`/api/admin/tasks`** — which in the App Router is **`src/app/api/admin/tasks/route.ts`** (or equivalent). The “more error communicate” will only show up after that file exists and is being hit.
