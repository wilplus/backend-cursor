# BFF fix: 403 on recording-metrics-chunk ("new row violates row-level security policy")

Use this in the **frontend/BFF repo** to fix the 403. The backend (Flask) does not need changes.

---

## What’s going wrong

The browser calls **POST /api/homework/session/:sessionId/recording-metrics-chunk**. The response is **403** with:

- `"Unauthorized"`
- `"new row violates row-level security policy"`

That message comes from **Supabase/Postgres** when an **INSERT** (or update) fails RLS. The Flask backend does **not** insert anything for this endpoint; it only reads the session and returns in-memory metrics. So the failing write is in the **BFF** (or in something the BFF calls).

---

## What to do in the BFF

### 1. Remove any Supabase write in this path

- Open the handler for **POST** `.../recording-metrics-chunk` (e.g. `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts`).
- If you use a shared **proxyBinary(path, req)** (or similar), check what it does: does it only proxy to the backend, or does it also call Supabase (e.g. `supabase.from('...').insert(...)`, Realtime, Storage)?
- **Remove** any Supabase insert/upsert/update for this endpoint. This route must **only** proxy the request to Flask and return Flask’s response. No writing to Supabase in this path.

### 2. Forward the student’s auth to Flask

- The request to the backend must include **Authorization: Bearer &lt;student_access_token&gt;**.
- If you use a server-side token (e.g. `getV2AccessToken()` from cookies/session), that must be the **current user’s** access token (student), not a global service key.
- If you use `proxyBinary`, ensure it forwards the incoming request’s **Authorization** header to the backend, or that it sets **Authorization** from the server-side student token (e.g. `getV2AccessToken()`).

---

## Reference implementation (pure proxy, no Supabase)

If you replace the current handler (or the part that uses proxyBinary for this route) with a **pure proxy** that does no Supabase calls, you can use this. Copy the file from the backend repo:

**From:** `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`  
**To:** `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts`

Adjust imports if your `getAuth` lives elsewhere (e.g. `../../../../../getAuth` → your path to `getAuth`).

That route:

- Uses **getV2AccessToken()** (student token from cookies/session).
- Sends **POST** to `{BACKEND}/v2/homework/session/:sessionId/recording-metrics-chunk` with that token and the request body/headers.
- Returns the backend response with CORS.
- Does **not** call Supabase.

---

## Checklist

- [ ] No Supabase insert/update in the recording-metrics-chunk route (or in proxyBinary when used for this path).
- [ ] Backend request has **Authorization: Bearer &lt;student_token&gt;** (from getV2AccessToken or forwarded from client).
- [ ] Smoke test: Final task step, dartboard on → **recording-metrics-chunk** returns **200** (no 403).

After this, the 403 and the RLS error should stop, with no backend or RLS changes.
