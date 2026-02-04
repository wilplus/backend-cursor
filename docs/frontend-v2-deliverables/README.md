# Frontend V2 Deliverables (legacy reference)

**The backend has one student flow only: homework** (warm-up → recording_1 → … → report). The classic v2 flow (universal questions, one recording) has been removed. Use **`docs/homework-bff-routes/`** for the homework BFF. This folder is reference only; session/recordings routes below are no longer served.

## What's included

| Item | Location to copy to |
|------|---------------------|
| V2 types | `src/lib/api/types-v2.ts` (or merge into `types.ts`) |
| API client | `src/lib/api/client-v2.ts` (calls `/api/*`) |
| BFF API routes | `src/app/api/...` (no v2; each `route.ts` as listed below) |
| Store additions | See **Store (session-store-v2)** section — patch your existing store |
| SessionCardV2 flow | See **SessionCardV2** section — wire UI to client + states |

## Backend base URL

Your BFF must proxy to the Flask backend. Set in env (e.g. `.env.local`):

```bash
NEXT_PUBLIC_BACKEND_URL=https://your-backend.up.railway.app
# or for local: http://localhost:5000
```

Use this when proxying (server-side only; do not expose service role keys to the client).

## Apply order

1. Add **types-v2.ts** and **client-v2.ts** under `src/lib/api/`.
2. Create **API routes** under `src/app/api/` (no v2 in path) — see **API route file mapping** below.
3. Update **session-store-v2.ts** — see **Store (session-store-v2)** section.
4. Update **SessionCardV2.tsx** — see **SessionCardV2** section.

## API route file mapping

Frontend calls `/api/*`; BFF proxies to backend `/v2/*`. Copy to these paths (no `v2` in folder name):

| Deliverable file | Copy to |
|------------------|---------|
| `api-routes/getAuth.ts` | `src/app/api/getAuth.ts` |
| `api-routes/universal-questions-route.ts` | `src/app/api/universal-questions/route.ts` |
| `api-routes/session-start-route.ts` | `src/app/api/session/start/route.ts` |
| `api-routes/session-status-route.ts` | `src/app/api/session/status/route.ts` |
| `api-routes/session-universal-answers-route.ts` | `src/app/api/session/[sessionId]/universal-answers/route.ts` |
| `api-routes/session-exercise-feedback-route.ts` | `src/app/api/session/[sessionId]/exercise-feedback/route.ts` |
| `api-routes/session-select-task-route.ts` | `src/app/api/session/[sessionId]/select-task/route.ts` |
| `api-routes/session-intent-route.ts` | `src/app/api/session/[sessionId]/intent/route.ts` |
| `api-routes/session-post-answers-route.ts` | `src/app/api/session/[sessionId]/post-answers/route.ts` |
| `api-routes/recordings-upload-route.ts` | `src/app/api/recordings/upload/route.ts` |

Put **getAuth.ts** at `src/app/api/getAuth.ts`. Adjust relative imports in the route files (e.g. `../getAuth`, `../../getAuth`, `../../../getAuth`) to match. Adapt `getV2AccessToken()` to your Supabase server auth (e.g. `getSession()` or createServerClient).

## BFF auth

Each API route must forward the user's Supabase access token to the backend. Typical pattern:

- Get session (e.g. `createServerComponentClient` or `getSession()` from `@supabase/ssr` / `@supabase/auth-helpers-nextjs`).
- Read `session?.access_token` and send header: `Authorization: Bearer <token>`.
- If no token, return 401.

All route files below assume you have a helper like `getAccessToken()` that returns the token or null (implement with your auth setup).
