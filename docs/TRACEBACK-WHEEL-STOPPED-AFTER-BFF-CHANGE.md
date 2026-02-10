# Trace-back: Wheel stopped after BFF recording-metrics-chunk change

## Change that coincided with the wheel stopping

We replaced the BFF handler for **POST .../recording-metrics-chunk** with a **pure proxy** (no Supabase) to fix the 403 "new row violates row-level security policy". After that change:

- The **403 on the chunk endpoint went away** (Supabase fix).
- The **wheel stopped updating** in real time.

So the wheel broke at that BFF change. Either the new proxy behaves differently from the old handler (e.g. `proxyBinary`), or a related frontend change broke the pipeline.

---

## What the new proxy does (reference route)

- Gets token via `getV2AccessToken()`, returns 401 if missing.
- Reads body as **`request.arrayBuffer()`**, forwards with **Content-Type: application/octet-stream**.
- Forwards only these headers **if present**: **X-Sample-Rate**, **X-Seq**, **X-T-Ms**, **X-Recording-Slot**, **X-Debug**.
- POSTs to `{BACKEND}/v2/homework/session/${sessionId}/recording-metrics-chunk` and returns the backend response.

Flask expects: **raw PCM bytes** in the body, and headers **X-Sample-Rate**, **X-Seq**, **X-T-Ms** (optional X-Debug). It does **not** read X-Chunk-Seq or X-Chunk-Start-Ms.

---

## What to check (in order)

### 1. Are chunk requests sent and what status do they get?

In the browser **Network** tab, on the step where the wheel is shown (e.g. Warm-up or Final task):

- Filter by **recording-metrics-chunk** (or the BFF path).
- Are there **repeated** POST requests while the wheel is visible?
- What **status** do they return: **200**, **400**, **401**, **404**, **409**?

- **No requests** → frontend is not sending chunks (pipeline not started, or torn down after the BFF change / re-render).
- **401** → BFF `getV2AccessToken()` is null (e.g. no session in BFF context); fix auth/cookies.
- **404** → Wrong URL; often **sessionId is undefined** (e.g. Next 15 `params` is a Promise and you must `await params` before using `params.sessionId`).
- **400** → Backend got invalid body (e.g. empty or not raw PCM); check that the frontend sends **binary PCM** and the BFF forwards it as-is (arrayBuffer).
- **200** → Backend is fine; the bug is in the **frontend** (response not used to update wheel state, or wrong component instance).

### 2. Body format: binary vs JSON

Flask expects **raw PCM16 bytes** in the body. If the frontend sends **JSON** (e.g. `{ pcm_base64: "..." }` or `{ pcm: [...] }`), the new BFF still forwards it as an arrayBuffer, but Flask will treat it as PCM and either return 400 (e.g. "Missing PCM body" if it fails a check) or return meaningless metrics. The old handler might have:

- Parsed JSON and sent raw bytes to the backend, or
- Sent the request as-is and the backend was different.

**Check:** What does the frontend actually send in the chunk request body (binary vs JSON)? If it’s JSON, the BFF must either decode and re-encode as binary before calling Flask, or the frontend must be changed to send raw PCM.

### 3. Header names: X-Seq / X-T-Ms vs X-Chunk-Seq / X-Chunk-Start-Ms

The reference proxy only forwards **X-Sample-Rate**, **X-Seq**, **X-T-Ms**, **X-Recording-Slot**, **X-Debug**. If the frontend sends **X-Chunk-Seq** or **X-Chunk-Start-Ms** instead of **X-Seq** / **X-T-Ms**, those are **not** forwarded, so Flask gets defaults (seq=0, t_ms=0). The wheel might still get a 200 response, but if the frontend or backend logic depends on seq/t_ms, behavior can change.

**Check:** In Network → a chunk request → **Request Headers**. Do you see **X-Seq** and **X-T-Ms**, or **X-Chunk-Seq** and **X-Chunk-Start-Ms**? If it’s the latter, either update the BFF to map them (e.g. X-Chunk-Seq → X-Seq, X-Chunk-Start-Ms → X-T-Ms) or change the frontend to send X-Seq and X-T-Ms.

### 4. Next.js 15: `params` is a Promise

If the BFF is on **Next 15**, **params** is a **Promise**. The reference route uses `params.sessionId` synchronously. If you didn’t change it to `const { sessionId } = await params;`, then **sessionId** can be **undefined**, the request URL becomes `.../recording-metrics-chunk` with no id or wrong path, and the backend returns **404**. That would stop the wheel after the new route was deployed.

**Check:** In the BFF route, do you have `const { sessionId } = await params;` (or equivalent) before building the URL?

### 5. Old handler vs new: what did proxyBinary do?

If you still have the old code (e.g. that used **proxyBinary**):

- Compare **body**: did it forward the raw request body unchanged, or did it transform it (e.g. JSON → binary)?
- Compare **headers**: did it forward **all** request headers, or a fixed set? If it forwarded all, the frontend’s X-Chunk-Seq / X-Chunk-Start-Ms would have been sent to Flask (which ignores them), so that wouldn’t explain the break unless the frontend relies on them in some other way.
- Compare **auth**: did the old path use the same token source as `getV2AccessToken()`? If the old one used a different auth (e.g. forwarded the browser’s Authorization header and the new one uses server-side token), behavior could differ.

---

## Summary

| Observation | Likely cause |
|-------------|--------------|
| No chunk requests in Network | Frontend pipeline not running or torn down (e.g. after applyStatusToState / re-render). |
| Chunk requests return 401 | BFF auth: getV2AccessToken() null. |
| Chunk requests return 404 | Wrong URL; often sessionId undefined (Next 15 params not awaited). |
| Chunk requests return 400 | Body not raw PCM (e.g. JSON) or empty. |
| Chunk requests return 200 but wheel static | Backend OK; frontend not updating wheel from response (state/callback/component). |
| Frontend sends X-Chunk-Seq / X-Chunk-Start-Ms | BFF doesn’t forward them; add mapping to X-Seq / X-T-Ms or change frontend. |

First confirm in Network whether chunk requests are sent and what status they return; then fix BFF (auth, params, body, headers) or frontend (pipeline lifecycle, wheel state update) accordingly.
