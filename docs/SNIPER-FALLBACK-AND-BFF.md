# Sniper: Why It Doesn’t Start & How to Fix (Like Before)

## What “before the big update” was

- **Wheel was client-side only:** The frontend used the browser’s `AnalyserNode` (or similar) to compute loudness/pace in real time. No backend call was required for the wheel to appear or update.
- **No BFF route:** There was no `sniper-metrics-chunk` (or `recording-metrics-chunk`) in the backend or in the Next.js BFF. The wheel worked without any `/api/homework/...` call for metrics.

## What changed (big update)

- Backend gained full Sniper: `sniper-metrics-chunk` (POST + GET), `sniper-session-complete`, scoring, adaptive baseline.
- If the frontend was updated to **call** the backend for the wheel, it now does e.g. `POST /api/homework/session/<id>/sniper-metrics-chunk`.
- If the **BFF does not have that route**, that request returns **404** and the frontend never gets a response → “Sniper never starts.”

## What can be wrong right now

1. **BFF route missing**  
   Next.js app has no `src/app/api/homework/session/[sessionId]/sniper-metrics-chunk/route.ts`.  
   → Request goes to Next, gets 404, backend is never hit.

2. **Frontend requires 200 from backend to show the wheel**  
   If the UI only shows the wheel after a successful response from `sniper-metrics-chunk`, then 404 = wheel never appears.

3. **Backend or DB issue**  
   If the BFF route exists and the request reaches the backend, a missing table (e.g. `user_sniper_profile`) or another error could have caused 500. The backend was updated to **never 500** on the chunk endpoint: on any internal error it now returns **200** with a static fallback payload so the frontend still gets `active: true` and can show the wheel.

## How to fix it “like before”

### Option A: Use backend Sniper (recommended when BFF is set up)

1. **Copy the BFF routes** from this repo into the Next.js app:
   - `docs/homework-bff-routes/session/[sessionId]/sniper-metrics-chunk/route.ts`  
     → `src/app/api/homework/session/[sessionId]/sniper-metrics-chunk/route.ts`
   - `docs/homework-bff-routes/session/[sessionId]/sniper-session-complete/route.ts`  
     → `src/app/api/homework/session/[sessionId]/sniper-session-complete/route.ts`
2. Fix import paths for `getAuth` and `proxyResponse` if your app keeps them elsewhere.
3. Ensure `NEXT_PUBLIC_BACKEND_URL` (or `BACKEND_URL`) is set so the BFF can call the backend.
4. Optional: Call **GET** `/api/homework/session/<id>/sniper-metrics-chunk` first; if 200, use backend Sniper; if 404, fall back to client-side (Option B).

### Option B: “Like before” – client-side-only wheel

- **Do not** call `POST /api/homework/session/<id>/sniper-metrics-chunk` for the wheel.
- Drive the wheel only from the browser (e.g. `AnalyserNode`, mic stream, local metrics). The backend is not involved; behavior matches “before the big update.”
- You can still call `sniper-session-complete` when the user finishes a practice (to store session means) if you want; the wheel itself stays client-side.

### Backend behavior after the fix

- **GET** `.../sniper-metrics-chunk`: returns 200 + `{ "ready": true, "active": true }` when the session exists (probe endpoint).
- **POST** `.../sniper-metrics-chunk`: always returns **200** with a valid JSON payload (either real metrics or a static fallback). No 500 on missing table or internal errors.
- If the frontend gets 404, the request never reached the backend → add or fix the BFF route (Option A) or switch to client-side only (Option B).

### session_sniper_metrics and session_id

- `session_sniper_metrics.session_id` has a foreign key to `v2_sessions(id)`. The BFF (or any client) must only call `POST .../sniper-session-complete` with a `session_id` that **already exists** in `v2_sessions` (e.g. the session was created by `POST /v2/homework/session/start` first). Otherwise the backend upsert into `session_sniper_metrics` will fail on the FK. In normal flow the student starts a session before recording, so the session exists when the client sends sniper-session-complete.
