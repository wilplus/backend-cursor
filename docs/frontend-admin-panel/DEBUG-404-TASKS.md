# Debugging 404 for /api/admin/tasks

Use this to find out **where** the request fails: wrong path, BFF error, or backend error.

## 1. Open Network tab and reproduce

1. Open DevTools → **Network**.
2. Filter by **Fetch/XHR** (or leave all).
3. Open the student profile so the app requests tasks (or click into "Select Focus Tasks").
4. Find the request whose URL ends with **`/tasks`** (or path contains `tasks`).
5. Click it and check **Headers** (Request URL, Request Method) and **Response** (status, body).

## 2. Interpret the response

### A) Status 404 and Response is **HTML** or **empty** or **No response body**

→ **The BFF route is not running.** Next.js is returning its default 404 page.

- **Cause:** The file is in the wrong place. Next.js only serves `/api/admin/tasks` if the handler is at **`src/app/api/admin/tasks/route.ts`** (App Router).
- **Fix:** Create or move the file to **`src/app/api/admin/tasks/route.ts`** (not under `api/v2/admin/...`). Restart the dev server.

### B) Status 404 and Response is **JSON** with an **`_debug`** field

→ **The BFF route ran**, but the **backend** returned 404.

- Check **Response → Preview** (or **Response** tab). You should see something like:
  - `_debug.backendStatus`: 404
  - `_debug.backendHost`: your backend host (e.g. `your-app.railway.app`)
- **Cause:** The BFF is calling the wrong backend URL, or the backend route `/v2/admin/tasks` is not registered / not reachable.
- **Fix:** Ensure `getBackendUrl()` returns the correct backend base URL (e.g. `https://your-backend.railway.app`). On the backend, ensure the Flask app registers the v2 blueprint and the route is `GET /v2/admin/tasks`.

### C) Response has header **`X-BFF-Route: admin-tasks`**

→ **The BFF route file at `api/admin/tasks/route.ts` was executed.**

- If status is **200** and body has `tasks: [...]`: everything worked.
- If status is **401**: `_debug.stage` will be `getAuth` → token missing or invalid.
- If status is **500** and `_debug.stage` is `getBackendUrl`: backend URL not set.
- If status is **500** and `_debug.stage` is `init`: exception in getAuth/getBackendUrl (see `_debug.message`).
- If status is **403** or **404** and body has `_debug.backendStatus`: the backend returned that; check backend URL and backend logs.

### D) Response has header **`X-Backend-Route: v2-admin-tasks`** (in the backend response, visible if BFF forwards headers)

→ The **backend** received the request. (The BFF may not forward this header; you see it if you call the backend directly.) So if the BFF returns 200 and the response has `tasks`, the backend also sent `X-Backend-Route: v2-admin-tasks`.

## 3. Sanity check: add a minimal admin route

To confirm that **`/api/admin/*`** is reachable at all:

1. Create **`src/app/api/admin/health/route.ts`** (or `ping/route.ts`):

```ts
import { NextResponse } from "next/server";
export async function GET() {
  return NextResponse.json({ ok: true, route: "admin/health" }, { headers: { "X-BFF-Route": "admin-health" } });
}
```

2. In the browser, open **`https://your-frontend-url/api/admin/health`** (or use Network when something triggers it).
3. If you get **404** on `/api/admin/health`: your **`api/admin`** folder or routing is wrong (e.g. wrong `app` directory or different Next.js structure).
4. If you get **200** with `{ "ok": true, "route": "admin/health" }`: `/api/admin/*` works; the issue is specific to **`/api/admin/tasks`** (file missing or wrong path, e.g. typo in folder name).

## 4. Checklist

- [ ] File exists at **`src/app/api/admin/tasks/route.ts`** (not `api/v2/admin/tasks`).
- [ ] Exports **GET** and **POST**.
- [ ] Import path for `getAuth` is correct (e.g. `../../getAuth` if getAuth is in `src/app/api/getAuth.ts`).
- [ ] Dev server restarted after adding/changing the file.
- [ ] In Network tab, the **request URL** is exactly **`/api/admin/tasks`** (same origin as the app).

## 5. Copy the route with diagnostics

Use the version that adds **`_debug`** and **`X-BFF-Route`** so you can see in the response whether the BFF ran and what the backend returned:

- **File:** `docs/frontend-admin-panel/api-routes/tasks-route.ts` (in the backend repo)
- **Copy to:** `src/app/api/admin/tasks/route.ts`
- Fix the `getAuth` import path for your project.

After copying, trigger the request again and read the **Response** body and **Response headers** in the Network tab; use section 2 above to interpret them.
