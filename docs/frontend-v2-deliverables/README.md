# Frontend V2 Deliverables

Copy these into your **Next.js frontend** repo so the v2 flow uses the real backend `/v2/*` endpoints.

## What's included

| Item | Location to copy to |
|------|---------------------|
| V2 types | `src/lib/api/types-v2.ts` (or merge into `types.ts`) |
| V2 API client | `src/lib/api/client-v2.ts` |
| BFF API routes | `src/app/api/v2/...` (each `route.ts` as listed below) |
| Store additions | See **Store (session-store-v2)** section — patch your existing store |
| SessionCardV2 flow | See **SessionCardV2** section — wire UI to v2 client + states |

## Backend base URL

Your BFF must proxy to the Flask backend. Set in env (e.g. `.env.local`):

```bash
NEXT_PUBLIC_BACKEND_URL=https://your-backend.up.railway.app
# or for local: http://localhost:5000
```

Use this when proxying (server-side only; do not expose service role keys to the client).

## Apply order

1. Add **types-v2.ts** and **client-v2.ts** under `src/lib/api/`.
2. Create **API routes** under `src/app/api/v2/` — see **API route file mapping** below.
3. Update **session-store-v2.ts** — see **Store (session-store-v2)** section.
4. Update **SessionCardV2.tsx** — see **SessionCardV2** section.

## API route file mapping

| Deliverable file | Copy to |
|------------------|---------|
| `api-routes/getAuth.ts` | `src/app/api/v2/getAuth.ts` |
| `api-routes/universal-questions-route.ts` | `src/app/api/v2/universal-questions/route.ts` |
| `api-routes/session-start-route.ts` | `src/app/api/v2/session/start/route.ts` |
| `api-routes/session-status-route.ts` | `src/app/api/v2/session/status/route.ts` |
| `api-routes/session-universal-answers-route.ts` | `src/app/api/v2/session/[sessionId]/universal-answers/route.ts` |
| `api-routes/session-exercise-feedback-route.ts` | `src/app/api/v2/session/[sessionId]/exercise-feedback/route.ts` |
| `api-routes/session-select-task-route.ts` | `src/app/api/v2/session/[sessionId]/select-task/route.ts` |
| `api-routes/session-intent-route.ts` | `src/app/api/v2/session/[sessionId]/intent/route.ts` |
| `api-routes/session-post-answers-route.ts` | `src/app/api/v2/session/[sessionId]/post-answers/route.ts` |
| `api-routes/recordings-upload-route.ts` | `src/app/api/v2/recordings/upload/route.ts` |

Put **getAuth.ts** at `src/app/api/v2/getAuth.ts`. Then the relative imports in the route files (e.g. `../getAuth`, `../../getAuth`, `../../../getAuth`) will resolve correctly. Adapt `getV2AccessToken()` to your Supabase server auth (e.g. `getSession()` or createServerClient).

## BFF auth

Each API route must forward the user's Supabase access token to the backend. Typical pattern:

- Get session (e.g. `createServerComponentClient` or `getSession()` from `@supabase/ssr` / `@supabase/auth-helpers-nextjs`).
- Read `session?.access_token` and send header: `Authorization: Bearer <token>`.
- If no token, return 401.

All route files below assume you have a helper like `getAccessToken()` that returns the token or null (implement with your auth setup).
