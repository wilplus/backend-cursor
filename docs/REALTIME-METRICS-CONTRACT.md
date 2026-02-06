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
- **Body:** Raw **PCM16 little-endian mono** at **16 kHz** (or rate set in header).
  - Frontend: capture via **AudioWorklet** (or ScriptProcessorNode); **resample 48k → 16k** on the client if needed; send chunks every **250–500 ms** for real-time feel.
- **Headers:**

| Header           | Required | Description |
|------------------|----------|-------------|
| `X-Sample-Rate`  | No       | Sample rate in Hz (default 16000). Backend accepts 8000–48000. |
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
| `f0_hz_mean`       | Mean fundamental frequency (pitch) over voiced frames, Hz. |
| `f0_hz_std`        | Std of F0 over voiced frames, Hz. |
| `intonation_proxy` | 0–1 from pitch variation (for intonation). |
| `pace_proxy`       | 0–1 from voiced activity (for pacing). |

**Frontend:** Apply EMA + rolling window (e.g. 2–6 s) to these values, then map to glow color/intensity. **Filler words** are not available in real time; use **pause/voiced balance** for live feedback. Whisper after full upload provides fillers for the report.

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

## Flow summary

1. User starts recording (e.g. for recording_1 or recording_2).
2. Frontend captures **PCM** (AudioWorklet), resamples to 16 kHz, sends chunks every 250–500 ms to this endpoint.
3. Backend returns features; frontend smooths and updates glow.
4. User stops recording; frontend uploads **full recording** (WebM/Opus) to **POST .../recording-1** or **.../recording-2** as today. Whisper + report pipeline unchanged.
