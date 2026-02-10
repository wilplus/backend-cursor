# Wheel still doesn’t work — checklist and fix

The wheel (real-time glow / metrics during recording) depends on: **BFF route** → **backend** → **frontend posting to BFF** and **updating the wheel from the response**. Use this checklist to find where it breaks.

---

## 1. Backend contract (this repo — already implemented)

- **URL:** `POST /v2/homework/session/:sessionId/recording-metrics-chunk`
- **Auth:** Required (Bearer token; same as other homework routes).
- **Body:** Raw binary PCM16 mono (no JSON). Optional: can be empty for testing; backend returns neutral.
- **Headers:**
  - `X-Sample-Rate` (optional, default 16000)
  - `X-Seq` (optional, chunk sequence)
  - `X-T-Ms` (optional, timestamp ms)
  - `X-Debug` (optional, `1` or `true` for extra `_debug` in response)
- **Session:** Must exist and `status` in `warm_up`, `task_block`, `final_task_ready`, or `post_questions`. If status is `completed` or missing → **409 INVALID_SESSION_STATE**.
- **Response 200:** JSON, e.g.:
  ```json
  { "seq": 0, "t_ms": 0, "voiced_ratio": 0.45, "pause_score": 0.72, "pause_detected": false, "pitch_variance": 0.5 }
  ```
  - **pause_score** (0–1): use this to drive the wheel (e.g. brightness or position). 1 = neutral/ideal.
  - **voiced_ratio** (0–1): fraction of recent frames that are voiced.

---

## 2. BFF: route and auth

- **Route must exist:**  
  `POST /api/homework/session/[sessionId]/recording-metrics-chunk`  
  (or your app’s equivalent same-origin path).
- **Must proxy to backend:**  
  `POST {BACKEND_URL}/v2/homework/session/:sessionId/recording-metrics-chunk`
- **Must forward:**
  - **Body:** as-is (binary / ArrayBuffer).
  - **Authorization:** `Bearer <student token>` (e.g. from `getV2AccessToken()` or your auth helper). If this is missing, backend returns **401** and the wheel gets nothing.
  - **Headers:** `X-Sample-Rate`, `X-Seq`, `X-T-Ms` (and optionally `X-Debug`). If the frontend sends `X-Chunk-Seq` / `X-Chunk-Start-Ms`, the BFF should map them to `X-Seq` / `X-T-Ms`.
- **Next 15:** If using Next 15, `params` can be a Promise — use `await params` and then read `sessionId` so the route doesn’t 404.

Reference implementation: **`docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`** in this repo. Copy/adapt into your BFF; fix the import path for `getV2AccessToken` / `getBackendUrl` to match your app.

---

## 3. Frontend: URL and when to send

- **Post to same-origin BFF only.**  
  Example: `POST /api/homework/session/${sessionId}/recording-metrics-chunk`.  
  Do **not** post to `http://127.0.0.1:7242/ingest/...` or any other host — that will fail in production (CORS / mixed content) and the wheel will never get 200.
- **Only when the wheel should be active:**  
  Start the chunk pipeline only when **step is 1 or 3** (warm_up or final_task_ready) **and** the recorder is active. Stop when the user leaves that step or stops recording. If you send chunks when the user is on step 2 (task_block) or 4 (post_questions), the backend may still accept (it allows those statuses), but usually the UI only shows the wheel on steps 1 and 3 — so start/stop should match that to avoid noise and 409s if you later tighten the backend.
- **Backoff / stop on error:** If the backend returns 4xx/5xx, don’t hammer the endpoint; back off or stop and show a neutral state.

---

## 4. Frontend: use the response

- On **200**, read the JSON body and update the wheel from **`pause_score`** (and optionally `voiced_ratio`).  
  Example: `setWheelValue(response.pause_score)` or map it to brightness/position. If you don’t update state from the response, the wheel will never move.

---

## 5. Verify in DevTools

1. Open the homework flow, go to **step 1** (warm-up recording) or **step 3** (final task recording).
2. Start speaking so the pipeline sends chunks.
3. In **Network**, filter for `recording-metrics-chunk` (or your BFF path).
4. You should see **POST** requests returning **200** and response body like:
   `{ "seq": ..., "t_ms": ..., "voiced_ratio": ..., "pause_score": ..., "pause_detected": ..., "pitch_variance": ... }`.
5. If you see **401** → BFF is not forwarding auth.
6. If you see **404** → BFF route missing or wrong path (or backend URL wrong).
7. If you see **409** → Session status not in allowed list (e.g. already completed); refetch status and only send chunks on step 1 or 3.
8. If you see **CORS** or **blocked** → Request is going to another origin; switch to same-origin BFF URL.

---

## 6. If it still doesn’t work — paste this

So we can close the last integration issue quickly, paste **one** failing request:

- **Request URL** (full)
- **Status code**
- **Response body** (JSON or text)
- (If you never see a request to `recording-metrics-chunk`) Confirm: “No request is sent to recording-metrics-chunk” and whether the pipeline is started only on step 1/3 and whether the frontend URL is the BFF (same-origin) URL.

---

## Summary checklist

| # | Check |
|---|--------|
| 1 | BFF has route `POST .../session/[sessionId]/recording-metrics-chunk` proxying to backend. |
| 2 | BFF forwards **Authorization: Bearer &lt;token&gt;** and body + headers (X-Sample-Rate, X-Seq, X-T-Ms). |
| 3 | Frontend posts to **same-origin** BFF URL only (no localhost ingest in production). |
| 4 | Chunk pipeline **starts** only on step 1 or 3 when recorder is active; **stops** when leaving step or stopping recording. |
| 5 | On 200, frontend updates the wheel from **response.pause_score** (and optionally voiced_ratio). |
