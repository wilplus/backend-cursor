# Backend prompt: frontend API paths (no `v2` in URL)

**Give this to your backend or another LLM** so they know how the frontend talks to the backend.

---

## Summary

- **Frontend** calls **`/api/admin/*`**, **`/api/session/*`**, **`/api/homework/*`**, **`/api/recordings/*`**, **`/api/universal-questions`** — **no `v2`** in the path. This is the only canonical frontend API surface.
- The **Next.js BFF** receives those requests and **proxies** to your backend at **`BASE_URL/v2/admin/*`**, **`BASE_URL/v2/session/*`**, **`BASE_URL/v2/homework/*`**, etc.
- **Backend:** Keep serving **`/v2/admin/*`**, **`/v2/session/*`**, **`/v2/homework/*`** as you do today. **No backend change is required** when the frontend uses `/api/...` without `v2`.

---

## Details

| Frontend calls (same origin) | BFF proxies to backend |
|-----------------------------|-------------------------|
| `GET /api/admin/tasks` | `GET BASE_URL/v2/admin/tasks` |
| `GET /api/admin/students` | `GET BASE_URL/v2/admin/students` |
| `GET /api/admin/students/:id` | `GET BASE_URL/v2/admin/students/:id` |
| `POST /api/session/start` | `POST BASE_URL/v2/session/start` |
| `POST /api/homework/session/start` | `POST BASE_URL/v2/homework/session/start` |
| … | … |

Auth is unchanged: BFF sends `Authorization: Bearer <supabase_access_token>` to the backend.

---

## If something breaks

- **404 (page/route):** The request never reached the BFF — check that the frontend has the route (e.g. `src/app/api/admin/tasks/route.ts`) and that the app was **redeployed** after adding it.
- **404 (JSON from API):** The BFF is calling the backend; the backend has no route for that path — implement the corresponding `/v2/...` endpoint in Flask.

Full admin contract: **`docs/ADMIN-PANEL-SYNC.md`**. Full path mapping: **`docs/API-PATHS-FRONTEND-TO-BACKEND.md`**.
