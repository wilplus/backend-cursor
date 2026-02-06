# Real-time metrics (Ambient Glow) — endpoint contract

Stateless **chunk-in → features-out** endpoint for real-time glow during recording. Frontend sends **raw PCM** chunks; backend returns raw + lightly normalized features. Frontend applies **EMA + rolling window** and maps to glow color/intensity.

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

---

## Response (200)

JSON with raw + lightly normalized features:

```json
{
  "seq": 42,
  "t_ms": 10500,
  "rms_db": -24.3,
  "voiced_ratio": 0.82,
  "pause_balance": 0.71,
  "f0_hz_mean": 146.0,
  "f0_hz_std": 18.2,
  "intonation_proxy": 0.63,
  "pace_proxy": 0.58
}
```

| Field              | Description |
|--------------------|-------------|
| `seq`              | Echo of request `X-Seq`. |
| `t_ms`             | Echo of request `X-T-Ms`. |
| `rms_db`           | RMS level in dB (approx -60 to 0). |
| `voiced_ratio`     | Fraction of chunk that is “voiced” (0–1). |
| `pause_balance`    | 0–1 score for pause/silence balance. Ideal is 15–20% pause (e.g. 0.15–0.20 silence); score is 1 when close to that, lower when too much or too little pause. Derived from `1 - voiced_ratio` with a tolerance band. |
| `f0_hz_mean`       | Mean fundamental frequency (pitch) over voiced frames, Hz. |
| `f0_hz_std`        | Std of F0 over voiced frames, Hz. |
| `intonation_proxy` | 0–1 from pitch variation (for intonation). |
| `pace_proxy`       | 0–1 from voiced activity (for pacing). |

**Frontend:** Apply EMA + rolling window (e.g. 2–6 s) to these values, then map to glow color/intensity. **Filler words** are not available in real time; use **pause_balance** and **voiced_ratio** for live feedback. Whisper after full upload provides fillers for the report.

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
- **Behavior:** Read `request.arrayBuffer()`, forward to backend with `Authorization` and headers `X-Sample-Rate`, `X-Seq`, `X-T-Ms`, `X-Recording-Slot`. Return backend JSON response. Do not parse the body as JSON; pass through as binary.

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

Expected (silence): low `voiced_ratio`, low `rms_db`, `intonation_proxy` and `pace_proxy` near 0, `pause_balance` may be high (lots of silence).

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
