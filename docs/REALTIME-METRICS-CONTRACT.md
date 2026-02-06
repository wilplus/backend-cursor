# Real-time metrics (Ambient Glow) — pause-only contract

**Single live value:** `pause_score` ∈ [0, 1] (1 = ideal pausing). **Brightness = function(pause_score).**

- **No pauses = bad.** **Too long / too many pauses = bad.** **Balanced pausing = good.**
- Backend is **stateful per session**: 10 s rolling window; pause events = continuous silent runs ≥ 200 ms.
- Frontend sends PCM chunks every 250–500 ms; backend returns `seq`, `t_ms`, `voiced_ratio`, `pause_score`.

---

## Endpoint

**POST** `/v2/homework/session/<session_id>/recording-metrics-chunk`

- **Auth:** Required. `Authorization: Bearer <supabase_access_token>`.
- **Session:** Must exist and belong to the user; session status must be one of `warm_up`, `task_block`, `final_task_ready`, `post_questions`.
- **Rate limit:** 120 requests per 60 seconds per (user_id, session_id). 429 if exceeded.

---

## Request

- **Content-Type:** `application/octet-stream` (binary body).
- **Body:** Raw **PCM16 little-endian mono**. Preferred **16 kHz**; backend accepts **48 kHz** or **44.1 kHz** and **resamples to 16 kHz** internally.
  - Send chunks every **250–500 ms** (4–10×/sec) for stable real-time feel.
- **Headers:**

| Header            | Required | Description |
|-------------------|----------|-------------|
| `X-Sample-Rate`   | No       | Sample rate in Hz (default 16000). Backend accepts 8000–48000. |
| `X-Seq`           | No       | Chunk sequence number (echoed in response). Default 0. |
| `X-T-Ms`          | No       | Client timestamp or sample offset in ms (echoed in response). Default 0. |
| `X-Debug`         | No       | `1` or `true` to include `_debug`: `pause_ratio`, `pauses_per_min`, `max_pause_s`, `window_time`. |

---

## Response (200)

```json
{
  "seq": 42,
  "t_ms": 10500,
  "voiced_ratio": 0.82,
  "pause_score": 0.91
}
```

| Field          | Description |
|----------------|-------------|
| `seq`          | Echo of request `X-Seq`. |
| `t_ms`         | Echo of request `X-T-Ms`. |
| `voiced_ratio` | Fraction of **this chunk** that is “voiced” (0–1). **Gate:** when &lt; 0.15, backend returns **neutral** (`pause_score` = 1) so the UI doesn’t punish pauses. |
| `pause_score`  | Single score 0–1: 1 = ideal pausing over the last 10 s; drops when pause ratio, pause frequency, or max pause length is off. |

With **X-Debug: 1** (or **true**):

```json
"_debug": {
  "pause_ratio": 0.18,
  "pauses_per_min": 10.2,
  "max_pause_s": 1.4,
  "window_time": 10.0
}
```

---

## What the backend measures (real time)

1. **VAD (voice activity):** Split audio into **20 ms** frames; compute RMS dB per frame. A frame is **silent** if `db < -45`.
2. **Pause event:** A **continuous silent run ≥ 200 ms** (shorter gaps are ignored).
3. **Rolling window:** Backend keeps the last **10 seconds** of frame-level silent/voiced state per **session_id** (stateful). Each chunk updates the window and evicts older frames.
4. From the window it computes:
   - **pause_ratio** = silent_time / window_time
   - **pauses_per_min** = number_of_pause_events / (window_time_sec / 60)
   - **max_pause_s** = longest pause event duration in the window

---

## Benchmarks (good range + bad extremes)

| Measure           | Good / target   | Bad (too low)       | Bad (too high)      |
|-------------------|-----------------|---------------------|---------------------|
| **pause_ratio**   | **0.12–0.35**   | &lt;0.08 (no phrasing) | &gt;0.35 (too many)  |
| **pauses_per_min**| **6–20 / min**  | &lt;4 (no breaks)     | &gt;20 (choppy)      |
| **max_pause_s**   | **≤ 2.5 s**     | —                   | **≥ 5.0 s** (hard fail) |

---

## How pause_score is computed (one number, two extremes bad)

- **A) Pause ratio score (band):** center = 0.20, radius = 0.15 → good roughly 0.05–0.35. `ratio_score = smoothstep(1 - |delta|)`.
- **B) Pause frequency score (band):** center = 11 pauses/min, radius = 9 → good roughly 2–20. `freq_score = smoothstep(1 - |delta|)`.
- **C) Long-pause score (penalty):** `long_score = 1 - clamp((max_pause_s - 2.5) / (5.0 - 2.5), 0, 1)`. So max_pause_s ≤ 2.5 → 1; ≥ 5 s → 0.
- **Final:** `pause_score = smoothstep( min(ratio_score, freq_score) * long_score )`.

So the score drops if: pauses are too rare, or too frequent, or one pause is too long.

---

## Silence gating

If **voiced_ratio &lt; 0.15** (user effectively not speaking in that chunk), the backend returns **pause_score = 1** (neutral). So the glow doesn’t flip or punish during intentional silence.

---

## Frontend: map pause_score → glow

- **Brightness = function(pause_score).** Keep hue constant (e.g. 140 green or 200 cool); users learn “brightness = quality”.
- **HSL example:** Hue 140, Saturation 70%, **Lightness = 22% + 50% × pause_score**. Shadow/glow intensity ∝ pause_score.
  - `pause_score ≈ 1` → bright + strong glow.
  - `pause_score ≈ 0` → dim circle, little or no glow.
- **Stability:** Update every 250 ms; optionally smooth with EMA: `pause_score_smooth = 0.2 * new + 0.8 * old`.
- **Gate:** If `voiced_ratio < 0.15`, either freeze last glow or fade toward neutral (backend already returns 1.0).

Optional: if you want to show **direction** (too few vs too many pauses), you can add a separate mode or second indicator; the current API only returns the single `pause_score`.

---

## Troubleshooting: glow always green / brightness never changes

If the glow stays the same (e.g. always green, same brightness) whether you’re silent, speaking, or pausing for 5 s, the **backend is not the cause** — it returns different `pause_score` values when you’re speaking. The issue is almost always in the **frontend**.

### 1. Check that the frontend uses the response

- **The glow must be driven by `response.pause_score`.** If the UI uses a fixed color/brightness or a different field, it will never change.
- **Concrete:** When you receive the JSON from the chunk endpoint, use **that** value to set the glow, e.g.:
  - `lightness = 22 + 50 * response.pause_score` (percent), or
  - `opacity = 0.3 + 0.7 * response.pause_score` for a glow layer.
- If your code never reads `response.pause_score` (or never applies it to the circle/glow element), the glow will not react.

### 2. Check that the endpoint is called and returns different values

- During recording, the frontend must **send PCM chunks** to `POST .../recording-metrics-chunk` every 250–500 ms and **use the JSON response**.
- **Verify:** Log the response (e.g. `console.log(response.pause_score, response.voiced_ratio)`) or temporarily show it on screen. When you speak with almost no pauses you should see **lower** `pause_score` (e.g. 0.2–0.5); when you add natural pauses, it should go up. If you never see different numbers, either the endpoint isn’t being called or the request/response path is broken (e.g. BFF not proxying, wrong URL).
- Use **X-Debug: 1** and log `response._debug` to see raw `pause_ratio`, `pauses_per_min`, `max_pause_s` and confirm they change when you change how you speak.

### 3. Why silence and “stop for 5 s” look the same as speaking

- **During silence** (no speech in the chunk), the backend returns **pause_score = 1** (neutral) so we don’t punish the user. So the glow will stay **bright** during silence if you map 1 → bright. That is by design.
- So: “silence → then speak → then 5 s silence” can all look similar if the frontend always shows “green” and never actually applies `pause_score` to brightness. Once the frontend **does** use `pause_score`:
  - While you’re **speaking with few pauses**, `pause_score` will drop → glow should get **dimmer**.
  - When you **stop for 5 s**, chunks become silence → we return 1.0 → glow can go bright again (or you can treat silence differently; see below).

### 4. If you want the glow to dim when the user isn’t speaking

- Backend returns **pause_score = 1** when `voiced_ratio < 0.15`. So “no speech” is currently treated as “good” and the glow stays bright.
- If you want the circle to **dim** when the user is silent (e.g. “waiting for you to speak”), use **voiced_ratio** in the frontend: e.g. if `voiced_ratio < 0.15` for several updates in a row, **fade the glow down** (or show a “waiting” state) instead of using the neutral 1.0 for brightness. That way: speaking → brightness from `pause_score`; long silence → dim.

**Summary:** The glow doesn’t change because the frontend isn’t updating the glow from `response.pause_score`. Wire the glow element’s brightness/lightness/opacity to `pause_score` (and optionally use `voiced_ratio` to dim during long silence), and verify with logging that the API is called and returns varying values.

---

## Errors

- **400** — Missing body or invalid input.
- **404** — Session not found or not in a recording state.
- **429** — Rate limit exceeded (120/min per user+session).
- **500** — Server error.

---

## BFF (Next.js)

- **Copy from:** `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`
- **Copy to:** `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts`
- **Behavior:** Read `request.arrayBuffer()`, forward to backend with `Authorization` and headers `X-Sample-Rate`, `X-Seq`, `X-T-Ms`, `X-Debug` (optional). Return backend JSON. Do not parse body as JSON; pass through as binary.

---

## Testing the chunk endpoint

1. Get a session and token (e.g. **POST /v2/homework/session/start**).
2. Create a small PCM file (e.g. 1 s silence at 16 kHz = 32000 bytes):

   ```bash
   dd if=/dev/zero of=pcm_1s_silence.bin bs=32000 count=1
   ```

3. Call the endpoint:

   ```bash
   curl -s -X POST "https://BACKEND_URL/v2/homework/session/SESSION_ID/recording-metrics-chunk" \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
     -H "Content-Type: application/octet-stream" \
     -H "X-Sample-Rate: 16000" \
     -H "X-Seq: 0" \
     -H "X-T-Ms: 0" \
     --data-binary @pcm_1s_silence.bin
   ```

   **Expected (silence):** low `voiced_ratio`; backend returns **neutral** (`pause_score`: 1).

---

## Flow summary

1. User starts recording. Frontend captures PCM (e.g. AudioWorklet), sends chunks every 250–500 ms to this endpoint.
2. Backend maintains a **10 s** rolling window per session; computes pause_ratio, pauses_per_min, max_pause_s; returns **pause_score** (and voiced_ratio, seq, t_ms).
3. Frontend maps **pause_score** to glow brightness (and optional EMA). When voiced_ratio &lt; 0.15, treat as neutral (freeze or fade).
4. User stops recording; frontend uploads full recording to **POST .../recording-1** or **.../recording-2** as today.
