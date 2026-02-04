# Homework flow BFF routes

If the student **"Start homework"** screen shows **"Backend returned invalid JSON"** with an HTML 404, the Next.js app has no route for `/api/homework/session/start`. The frontend calls `/api/homework/*`; the BFF must proxy to the backend at `BASE_URL/v2/homework/*`.

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
