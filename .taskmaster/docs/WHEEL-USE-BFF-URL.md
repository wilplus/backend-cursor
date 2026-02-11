# Wheel: call BFF (same-origin), not the backend URL

**Two ways the wheel can get data:**

- **Browser-only (loudness & pace):** Mic → AudioContext → AnalyserNode → RMS (loudness) and voiced ratio → WPM (pace). No fetch, no chunks, no backend. Example: `useRealtimeStrengthPace`. If your wheel only uses this, you don't need the metrics-chunk endpoint.
- **Pause-based (from backend):** Send PCM chunks to the BFF → backend returns `pause_score` (and optionally `voiced_ratio`). Use the BFF URL so the browser doesn't do a cross-origin request and CORS doesn't block.

The rest of this doc applies only when you use the **metrics-chunk** endpoint for pause (or other server-side metrics).

---

## 1. BFF route (server)

Ensure the **BFF route** exists in your **frontend** app so the server can proxy to the backend:

- **Path:** `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts` (or your app's equivalent under `api/`).
- **Content:** Copy from this repo:  
  `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`  
  Adjust the `getAuth` import path to match your project (e.g. `@/app/api/getAuth` or relative to the route).

That route receives the POST from the browser, adds `Authorization: Bearer <token>`, and forwards to `getBackendUrl()/v2/homework/session/:sessionId/recording-metrics-chunk`.

---

## 2. Client-side wheel (browser)

In the component that sends PCM chunks (e.g. during recording in step 1 or 3), the **fetch URL must be same-origin** — i.e. your BFF path, **not** the backend host.

**Wrong (cross-origin, CORS can block):**
```ts
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:5000";
fetch(`${backendUrl}/v2/homework/session/${sessionId}/recording-metrics-chunk`, { ... });
```

**Correct (same-origin, no CORS):**
```ts
// Relative URL = same origin as the page (e.g. https://yourapp.vercel.app or http://localhost:3000)
const url = `/api/homework/session/${sessionId}/recording-metrics-chunk`;
fetch(url, {
  method: "POST",
  headers: {
    "Content-Type": "application/octet-stream",
    "X-Sample-Rate": "16000",
    "X-Seq": String(seq),
    "X-T-Ms": String(tMs),
    // Do NOT set Authorization here: the BFF adds it from the server-side token.
  },
  body: pcmArrayBuffer,
  credentials: "include", // if you use cookies for auth
});
```

Use the **response** (e.g. `response.pause_score`) to drive the wheel. No backend URL in the browser.

---

## 3. Checklist

- [ ] BFF route exists at `api/homework/session/[sessionId]/recording-metrics-chunk` (or your API base + that path).
- [ ] Wheel component uses **only** a relative URL like `/api/homework/session/${sessionId}/recording-metrics-chunk` (no `NEXT_PUBLIC_BACKEND_URL` or `127.0.0.1:5000` in the wheel fetch).
- [ ] BFF has access to the token (e.g. `getV2AccessToken()` from cookies/session) so it can send `Authorization: Bearer <token>` to the backend.

After this, the browser only talks to your app's origin; the BFF talks to the backend server-side, so CORS does not apply to that call.
