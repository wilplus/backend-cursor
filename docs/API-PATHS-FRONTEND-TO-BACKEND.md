# API paths: how the frontend talks to the backend

Use this when working on the backend or with another LLM so the API path mapping is clear. **The backend does not need to change**; this doc describes what the frontend calls and how the BFF proxies to us.

---

## What the frontend uses

The **frontend** does **not** use `v2` in its API paths. All requests go to:

- **Admin:** `/api/admin/*` (e.g. `/api/admin/tasks`, `/api/admin/students`, `/api/admin/students/:id/warm-up-tasks`)
- **Homework (student, only flow):** `/api/homework/session/start`, `/api/homework/session/status`, `/api/homework/session/:id/warm-up-task`, `/api/homework/session/:id/recording-1`, etc.

The **Next.js BFF** (API routes under `src/app/api/`) receives these requests and **proxies to the backend** with the path under **`/v2/`**:

| Frontend calls | BFF proxies to backend |
|----------------|------------------------|
| `GET /api/admin/tasks` | `GET BASE_URL/v2/admin/tasks` |
| `GET /api/admin/students` | `GET BASE_URL/v2/admin/students` |
| `GET /api/admin/students/:id` | `GET BASE_URL/v2/admin/students/:id` |
| `POST /api/homework/session/start` | `POST BASE_URL/v2/homework/session/start` |
| `GET /api/homework/session/status` | `GET BASE_URL/v2/homework/session/status` |
| `GET /api/homework/session/:id/warm-up-task` | `GET BASE_URL/v2/homework/session/:id/warm-up-task` |
| … | … |

---

## Backend: no change required

**The backend stays as it is.** Keep serving:

- **Admin:** `GET/POST/PUT/DELETE /v2/admin/students`, `/v2/admin/tasks`, `/v2/admin/post-recording-questions`, `/v2/admin/metrics`, `/v2/admin/students/:id/warm-up-tasks`, etc.
- **Student (only flow):** **Homework** — `/v2/homework/session/start`, `/v2/homework/session/status`, `/v2/homework/session/:id/warm-up-task`, `/v2/homework/session/:id/recording-1`, `/v2/homework/session/:id/metric-answers`, `/v2/homework/session/:id/recording-2`, `/v2/homework/session/:id/questions`, `/v2/homework/session/:id/post-answers`.

Auth is unchanged: the BFF sends `Authorization: Bearer <supabase_access_token>` to the backend. The backend still validates the JWT and enforces admin for `/v2/admin/*`.

---

## Summary

- **Frontend:** Calls `/api/admin/*` and `/api/homework/*` (no `v2` in path). Student flow is homework only.
- **BFF:** Proxies to `BASE_URL/v2/admin/*` and `BASE_URL/v2/homework/*`.
- **Backend:** Serves `/v2/admin/*` and `/v2/homework/*` only for the app flow; classic v2 session/recordings/universal-questions removed.

For the full admin API contract (students, tasks, warm-up tasks, metrics, overrides, speaker profile, etc.), see **`docs/ADMIN-PANEL-SYNC.md`**.
