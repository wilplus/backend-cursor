# Homework flow BFF routes

**404 on "start"?** The browser is calling your Next.js app (e.g. `POST /api/homework/session/start`), and that route does not exist yet. Next.js returns 404. Fix: add the BFF route by copying `session/start/route.ts` from this folder to **`src/app/api/homework/session/start/route.ts`** in your frontend repo. Also add **`session/status/route.ts`** → **`src/app/api/homework/session/status/route.ts`** so the status check on page load works.

If the student **"Start homework"** screen shows **"Backend returned invalid JSON"** with an HTML 404, the same cause applies: the Next.js app has no route for `/api/homework/session/start`. The frontend calls `/api/homework/*`; the BFF must proxy to the backend at `BASE_URL/v2/homework/*`.

## Show recording right away (no click)

On the Homework page, **do not** show a "Start homework" button. On page load:

1. Call **`GET /api/homework/session/status`**. If the response has `has_active_session` and `session`, render the current step (warm-up + record, or task block, etc.) using `session.id` and `session.status`.
2. If there is **no** active session, call **`POST /api/homework/session/start`** in the same load (e.g. in `useEffect`). Use the response (`session_id`, `status`, `warm_up_task`) to render the warm-up task and record button immediately so the user can record without clicking anything.

## Fix

Copy the route files from this folder into your Next.js app so the paths match. Ensure **`getAuth`** is at **`src/app/api/getAuth.ts`** (same as admin routes); if it lives elsewhere, adjust the import in each file (e.g. `../../../getAuth` or `../../../../getAuth` so it resolves to your getAuth module).

## File mapping

| Copy from (this repo) | Copy to (your Next.js app) |
|----------------------|----------------------------|
| `session/start/route.ts` | `src/app/api/homework/session/start/route.ts` |
| `session/status/route.ts` | `src/app/api/homework/session/status/route.ts` |
| `session/[sessionId]/warm-up-task/route.ts` | `src/app/api/homework/session/[sessionId]/warm-up-task/route.ts` |
| `session/[sessionId]/recording-1/route.ts` | `src/app/api/homework/session/[sessionId]/recording-1/route.ts` |
| `session/[sessionId]/metric-answers/route.ts` | `src/app/api/homework/session/[sessionId]/metric-answers/route.ts` |
| `session/[sessionId]/recording-2/route.ts` | `src/app/api/homework/session/[sessionId]/recording-2/route.ts` |
| `session/[sessionId]/questions/route.ts` | `src/app/api/homework/session/[sessionId]/questions/route.ts` |
| `session/[sessionId]/post-answers/route.ts` | `src/app/api/homework/session/[sessionId]/post-answers/route.ts` |

## Import path for getAuth

The examples use:

- **`session/start/route.ts`** and **`session/status/route.ts`**: `import { ... } from "../../../../getAuth"` (assumes `getAuth` at `src/app/api/getAuth.ts`).
- **`session/[sessionId]/.../route.ts`**: `import { ... } from "../../../../../getAuth"`.

If your `getAuth` is at `src/app/api/getAuth.ts`, the relative path from `src/app/api/homework/session/start/route.ts` is up 4 levels → `../../../../getAuth`. From `src/app/api/homework/session/[sessionId]/warm-up-task/route.ts` it's up 5 levels → `../../../../../getAuth`.

## Backend

The backend (this repo) already exposes `POST /v2/homework/session/start`, `GET /v2/homework/session/status`, etc. No backend change is needed. Set `NEXT_PUBLIC_BACKEND_URL` (or `BACKEND_URL`) in your frontend env to the backend base URL.
