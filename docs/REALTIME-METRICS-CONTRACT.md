# Real-time metrics (Ambient Glow) — endpoint contract

Stateless **chunk-in → score/delta-out** endpoint for real-time glow during recording. Backend returns an **unambiguous mathematical contract**: per metric, a **score** in [0,1] (how good) and a **delta** in [-1,+1] (which direction / which extreme). Frontend smooths, picks **dominant** metric + **delta sign**, and maps to color.

---

## Endpoint

**POST** `/v2/homework/session/<session_id>/recording-metrics-chunk`

- **Auth:** Required. `Authorization: Bearer <supabase_access_token>`.
- **Session:** Must exist and belong to the user; session status must be one of `warm_up`, `task_block`, `final_task_ready`, `post_questions` (i.e. “during recording”).
- **Rate limit:** 120 requests per 60 seconds per (user_id, session_id). 429 if exceeded.

---

## Request

- **Content-Type:** `application/octet-stream` (binary body).
- **Body:** Raw **PCM16 little-endian mono**. Preferred **16 kHz**; backend also accepts **48 kHz** or **44.1 kHz** and **resamples to 16 kHz** internally, so clients can send 48k/44.1k without client-side resampling.
  - Frontend: capture via **AudioWorklet** (or ScriptProcessorNode); send chunks every **250–500 ms** for real-time feel. Optionally resample to 16k on the client, or send 48k/44.1k and let the backend resample.
- **Headers:**

| Header           | Required | Description |
|------------------|----------|-------------|
| `X-Sample-Rate`  | No       | Sample rate in Hz (default 16000). Backend accepts 8000–48000; 48k and 44.1k are resampled to 16k. |
| `X-Seq`          | No       | Chunk sequence number (echoed in response). Default 0. |
| `X-T-Ms`         | No       | Client timestamp or sample offset in ms (echoed in response). Default 0. |
| `X-Recording-Slot` | No     | `recording_1` or `recording_2` (for future use; not required for stateless). |
| `X-Debug`        | No       | `1` or `true` to include `_debug` in response: `silence_ratio`, `std_cents`, `wpm_proxy` (for calibration). |

---

## Response (200)

JSON with **score** [0,1] and **delta** [-1,+1] per metric, plus `seq` and `voiced_ratio`:

```json
{
  "seq": 42,
  "t_ms": 10500,
  "voiced_ratio": 0.82,
  "pacing_score": 0.85,
  "pacing_delta": -0.33,
  "intonation_score": 0.72,
  "intonation_delta": 0.08,
  "pause_score": 0.91,
  "pause_delta": -0.25
}
```

| Field               | Description |
|---------------------|-------------|
| `seq`               | Echo of request `X-Seq`. |
| `t_ms`              | Echo of request `X-T-Ms`. |
| `voiced_ratio`      | Fraction of chunk that is “voiced” (0–1). **Gate:** when &lt; 0.15, backend returns neutral (all score=1, delta=0) so the UI doesn’t punish pauses. |
| `pacing_score`      | 0–1 how good pacing is (middle band good; too slow or too fast bad). |
| `pacing_delta`      | -1..+1: &lt;0 = too slow, &gt;0 = too fast. |
| `intonation_score`  | 0–1 how good intonation is (middle band good; monotone or chaotic bad). |
| `intonation_delta`  | -1..+1: &lt;0 = too flat/monotone, &gt;0 = too chaotic. |
| `pause_score`       | 0–1 how good pause balance is (ideal ~20% silence; too few or too many pauses bad). |
| `pause_delta`       | -1..+1: &lt;0 = too few pauses, &gt;0 = too many pauses. |

With **X-Debug: 1** (or **X-Debug: true**), the response includes:

```json
"_debug": {
  "silence_ratio": 0.18,
  "std_cents": 65.2,
  "wpm_proxy": 138.0
}
```

---

## Core math (backend contract)

For each metric the backend:

1. Picks a **raw measurement** \(x\) from the PCM chunk.
2. Defines an **ideal target band**: center \(c\), half-width \(r\) (good zone = \(c \pm r\)).
3. Computes **delta** (signed, which extreme): \(\delta = \text{clamp}((x - c) / r,\,-1,\,+1)\).
4. Computes **score** (middle good, extremes bad): \(\text{rawScore} = 1 - |\delta|\), then \(\text{score} = \text{smoothstep}(\text{rawScore}) = t^2(3-2t)\).

So **both extremes are bad**; only the band is “good”.

### Raw measurements and bands (v1)

| Metric     | Raw \(x\) | Center \(c\) | Radius \(r\) | Interpretation |
|------------|-----------|--------------|--------------|----------------|
| **Pause** | silence_ratio (1 − voiced_ratio) | 0.20 | 0.12 | Good ~8–32% silence. |
| **Intonation** | std(F0 in cents, relative to median) | 70 | 50 | Good ~20–120 cents std. |
| **Pacing** | wpm_proxy (envelope peaks → syllables → WPM) | 145 | 30 | Good ~115–175 WPM proxy. |

### Silence gating

If `voiced_ratio < 0.15`, the backend returns **neutral**: all `*_score = 1`, all `*_delta = 0`. So the glow doesn’t flip during intentional pauses.

---

## Frontend: smoothing and color

1. **Gate:** Ignore updates when `voiced_ratio < 0.15` (or use backend’s neutral as-is).
2. **Smooth:** EMA or rolling window (e.g. 2–6 s) over the three scores (and optionally deltas).
3. **Dominant metric:** Pick `dominant = argmin(smoothed_scores)` (the worst of the three).
4. **Color by dominant + delta sign:**
   - **Green** when all three scores are high (e.g. min score &gt; 0.85).
   - Otherwise choose hue from dominant and delta:
     - **Pacing** dominant: delta&gt;0 → red (fast), delta&lt;0 → blue (slow).
     - **Intonation** dominant: delta&lt;0 → grey (monotone), delta&gt;0 → purple (chaotic).
     - **Pause** dominant: delta&lt;0 → yellow (too few pauses), delta&gt;0 → orange (too many pauses).

This gives “math → behavior” with no ambiguity: red (or the right hue) happens when a metric leaves the good band and delta indicates which side.

---

## Errors

- **400** — Missing body or invalid input.
- **404** — Session not found or not in a recording state.
- **429** — Rate limit exceeded (120/min per user+session).
- **500** — Server error.

---

## BFF (Next.js)

If the frontend calls `/api/homework/...`, add a route that **proxies the binary body and headers** to the backend. Example in this repo:

- **Copy from:** `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`
- **Copy to:** `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts`
- **Behavior:** Read `request.arrayBuffer()`, forward to backend with `Authorization` and headers `X-Sample-Rate`, `X-Seq`, `X-T-Ms`, `X-Recording-Slot`, `X-Debug` (optional). Return backend JSON response. Do not parse the body as JSON; pass through as binary.

---

## Testing the chunk endpoint

You can hit the endpoint with `curl` using a small PCM file and a valid session + token.

### 1. Get a session and token

- Log in (or use your app) to obtain a Supabase `access_token`.
- Call **POST /v2/homework/session/start** (or use an existing session from **GET /v2/homework/session/status**) to get a `session_id`.

### 2. Create a small PCM file (e.g. 1 second of silence at 16 kHz)

PCM16 mono 16 kHz = 32000 bytes per second (2 bytes × 16000 samples).

```bash
# 1 second of silence (zeros): 32000 bytes
dd if=/dev/zero of=pcm_1s_silence.bin bs=32000 count=1

# Or half a second (16000 bytes)
dd if=/dev/zero of=pcm_0.5s_silence.bin bs=16000 count=1
```

### 3. Call the endpoint

Replace `BACKEND_URL`, `SESSION_ID`, and `YOUR_ACCESS_TOKEN` with real values.

```bash
curl -s -X POST "https://BACKEND_URL/v2/homework/session/SESSION_ID/recording-metrics-chunk" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Sample-Rate: 16000" \
  -H "X-Seq: 0" \
  -H "X-T-Ms: 0" \
  --data-binary @pcm_1s_silence.bin
```

Expected (silence): low `voiced_ratio`; backend returns **neutral** (all `*_score`: 1, all `*_delta`: 0).

To test **48 kHz** (backend resamples to 16k internally):

```bash
# 1 second at 48 kHz = 96000 bytes
dd if=/dev/zero of=pcm_1s_48k.bin bs=96000 count=1

curl -s -X POST "https://BACKEND_URL/v2/homework/session/SESSION_ID/recording-metrics-chunk" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Sample-Rate: 48000" \
  -H "X-Seq: 0" \
  -H "X-T-Ms: 0" \
  --data-binary @pcm_1s_48k.bin
```

### 4. Via BFF (if your frontend uses Next.js API routes)

Use the same curl but target your BFF and include the auth cookie or header your BFF expects:

```bash
curl -s -X POST "https://your-app.vercel.app/api/homework/session/SESSION_ID/recording-metrics-chunk" \
  -H "Content-Type: application/octet-stream" \
  -H "X-Sample-Rate: 16000" \
  -H "X-Seq: 0" \
  -H "X-T-Ms: 0" \
  --data-binary @pcm_1s_silence.bin
```

(If your BFF reads the token from a cookie, omit `Authorization` when calling the BFF; the BFF adds it when proxying to the backend.)

---

## Flow summary

1. User starts recording (e.g. for recording_1 or recording_2).
2. Frontend captures **PCM** (AudioWorklet), resamples to 16 kHz, sends chunks every 250–500 ms to this endpoint.
3. Backend returns features; frontend smooths and updates glow.
4. User stops recording; frontend uploads **full recording** (WebM/Opus) to **POST .../recording-1** or **.../recording-2** as today. Whisper + report pipeline unchanged.
