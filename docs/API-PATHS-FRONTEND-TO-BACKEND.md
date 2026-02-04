# API paths: how the frontend talks to the backend

Use this when working on the backend or with another LLM so the API path mapping is clear. **The backend does not need to change**; this doc describes what the frontend calls and how the BFF proxies to us.

---

## What the frontend uses

The **frontend** does **not** use `v2` in its API paths. All requests go to:

- **Admin:** `/api/admin/*` (e.g. `/api/admin/tasks`, `/api/admin/students`, `/api/admin/students/:id/warm-up-tasks`)
- **Session (student):** `/api/session/*` (e.g. `/api/session/start`, `/api/session/status`, `/api/session/:id/universal-answers`)
- **Recordings:** `/api/recordings/upload`
- **Universal questions:** `/api/universal-questions`
- **Homework (student):** `/api/homework/session/start`, `/api/homework/session/status`, `/api/homework/session/:id/warm-up-task`, `/api/homework/session/:id/recording-1`, etc.

The **Next.js BFF** (API routes under `src/app/api/`) receives these requests and **proxies to the backend** with the path under **`/v2/`**:

| Frontend calls | BFF proxies to backend |
|----------------|------------------------|
| `GET /api/admin/tasks` | `GET BASE_URL/v2/admin/tasks` |
| `GET /api/admin/students` | `GET BASE_URL/v2/admin/students` |
| `GET /api/admin/students/:id` | `GET BASE_URL/v2/admin/students/:id` |
| `POST /api/session/start` | `POST BASE_URL/v2/session/start` |
| `POST /api/homework/session/start` | `POST BASE_URL/v2/homework/session/start` |
| `GET /api/homework/session/status` | `GET BASE_URL/v2/homework/session/status` |
| `GET /api/homework/session/:id/warm-up-task` | `GET BASE_URL/v2/homework/session/:id/warm-up-task` |
| … | … |

---

## Backend: no change required

**The backend stays as it is.** Keep serving:

- **Admin:** `GET/POST/PUT/DELETE /v2/admin/students`, `/v2/admin/tasks`, `/v2/admin/post-recording-questions`, `/v2/admin/metrics`, `/v2/admin/students/:id/warm-up-tasks`, etc.
- **Student (classic):** `/v2/session/start`, `/v2/session/status`, `/v2/session/:id/universal-answers`, `/v2/recordings/upload`, `/v2/session/:id/post-answers`, etc.
- **Homework:** `/v2/homework/session/start`, `/v2/homework/session/:id/warm-up-task`, `/v2/homework/session/:id/recording-1`, `/v2/homework/session/:id/metric-answers`, `/v2/homework/session/:id/recording-2`, `/v2/homework/session/:id/questions`, `/v2/homework/session/:id/post-answers`, etc.

Auth is unchanged: the BFF sends `Authorization: Bearer <supabase_access_token>` to the backend. The backend still validates the JWT and enforces admin for `/v2/admin/*`.

---

## Summary

- **Frontend:** Calls `/api/admin/*`, `/api/session/*`, `/api/homework/*`, `/api/recordings/*`, `/api/universal-questions` (no `v2` in the path).
- **BFF:** Proxies to `BASE_URL/v2/admin/*`, `BASE_URL/v2/session/*`, `BASE_URL/v2/homework/*`, `BASE_URL/v2/recordings/*`, `BASE_URL/v2/universal-questions`.
- **Backend:** Serves `/v2/admin/*`, `/v2/session/*`, `/v2/homework/*`, `/v2/recordings/*`, `/v2/universal-questions`. No backend change needed when the frontend drops `v2` from its URLs.

For the full admin API contract (students, tasks, warm-up tasks, metrics, overrides, speaker profile, etc.), see **`docs/ADMIN-PANEL-SYNC.md`**.
