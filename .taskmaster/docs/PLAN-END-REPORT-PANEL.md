# Implementation plan: End report panel (player + graph + text)

**Goal:** On step 5 (end report), show a single container with: **(1) recording player** (final/second recording), **(2) performance score graph**, **(3) report text** — in that order. Data must survive refresh and return visits; playback URL must not rely on long-lived stored URLs.

---

## 1. Principles

- **Single source of truth for step 5:** A dedicated **report endpoint** returns everything needed to render the panel. Step 5 does not depend on “we just did post-answers in this tab.”
- **Fresh playback URL on demand:** Do not persist `recording_2_audio_url`. Persist only a stable id (`recording_2_id`). Generate a **new signed URL** when the report is requested (or when playback is requested).
- **Explicit “final” recording:** Server-side, the homework session’s **final** recording is already defined: `v2_sessions.recording_2_id`. No new role/sequence field required; use this consistently in the report API.
- **Scores for the graph:** Backend already has `performance_score_1` (warm-up), `performance_score_2` (final), `performance_score_end` (average) on the session at report time. Expose them in a clear shape for the frontend chart.

---

## 2. Backend

### 2.1 New report endpoint

**`GET /v2/homework/session/:sessionId/report`** (auth required, owner-only)

**Behavior:**

- Load session by `session_id` and `user_id`. If not found or not owner → 404.
- Session must be **completed** (status = `completed`) to return report data. If not completed → 404 or 409 with a clear code (e.g. `REPORT_NOT_READY`).
- **Final recording** = `session.recording_2_id` (explicit; no ambiguity).
- Load recording row by `recording_2_id` and `user_id`. If missing → return report without `final_recording.audio_url` (or omit `final_recording`).
- From recording row read `storage_path`. Call `db.create_signed_url(bucket, storage_path, expiry)` (e.g. same `SIGNED_URL_EXPIRY_SECONDS` as elsewhere, or a dedicated shorter expiry for report playback). Do **not** store this URL; generate it on every request.
- Build response (see contract below).

**Response contract (JSON):**

```json
{
  "report_text": "...",
  "scores": {
    "warmup": 72,
    "final": 84,
    "overall": 80
  },
  "final_recording": {
    "id": "uuid",
    "audio_url": "https://...signed..."
  }
}
```

- `report_text`: From session (e.g. `context_long` or report row); same content the user saw when they completed post-answers.
- `scores`: All 0–100 integers for the chart.
  - `warmup` = `performance_score_1 * 100`
  - `final` = `performance_score_2 * 100`
  - `overall` = `performance_score_end * 100`
- `final_recording.id`: `recording_2_id` (so frontend can refetch playback later if needed).
- `final_recording.audio_url`: Fresh signed URL for this request. Omit if recording missing or storage_path empty or signed URL creation fails (frontend shows “Playback not available”).

**Idempotency:** GET; no side effects. Safe to call on every step-5 mount or refresh.

### 2.2 Playback URL expiry and optional dedicated endpoint

- Signed URLs expire (e.g. 1 hour). So the report response is valid for a limited time; after that, the frontend can call a **playback-only** endpoint to get a new URL without refetching the whole report.
- **Optional but recommended:** **`GET /v2/homework/session/:sessionId/recording-2/playback-url`** (or **`GET /v2/recordings/:recordingId/playback-url`**)
  - Returns `{ "audio_url": "https://..." }` with a new signed URL.
  - Use when: report was loaded earlier and the embedded `audio_url` has expired (e.g. user refreshes or returns later). Frontend stores only `session_id` or `recording_2_id`; when `<audio>` fails (or on load if URL is “old”), call this to get a fresh URL and set `src` again.

### 2.3 Audio playback robustness (storage/CORS)

- **Content-Type:** Ensure object storage serves the file with correct type (e.g. `audio/webm`, `audio/mpeg`) so `<audio>` can play.
- **CORS:** If the signed URL is on a different origin than the app, allow `GET` from the frontend origin so the browser can load the audio.
- **Range requests:** Storage (e.g. S3/Supabase) should support `Range` so seeking in the player works. Document that this is required for a good UX.

### 2.4 “Final” recording definition (no schema change)

- **Current model:** `v2_sessions.recording_2_id` is the second (final) recording of the homework flow. Use this everywhere for “the recording that goes with the end report.”
- No new column or role needed; document in API spec: “For the report panel, the final recording is the one referenced by `session.recording_2_id`.”

---

## 3. BFF (Next.js API routes)

- **`GET /api/homework/session/[sessionId]/report`**
  - Proxies to backend `GET /v2/homework/session/:sessionId/report` with auth (Bearer token from session).
  - Returns the same JSON. No caching of `audio_url` in BFF.

- **Optional:** **`GET /api/homework/session/[sessionId]/recording-2/playback-url`** (or **`/api/recordings/[id]/playback-url`**)
  - Proxies to backend playback-url endpoint; returns `{ audio_url }` for refreshing the player.

---

## 4. Frontend

### 4.1 Data flow for step 5

- **On mount of the end-report panel (step 5):**
  - If we have `sessionId` (from state or from persisted “report” context), call **`GET /api/homework/session/:sessionId/report`**.
  - Store result in component state (or React Query/SWR): `reportText`, `scores`, `finalRecording`.
- **After post-answers success (same tab):**
  - Can either (a) redirect/navigate to step 5 and let the panel fetch the report (recommended), or (b) use the post-answers response to prefill and still fetch report once so refresh is correct. Prefer (a) so one code path.
- **Persistence / “back later”:**
  - Persist only `sessionId` (and maybe `session_id` in sessionStorage for “last report” so we know which session to fetch). Do **not** persist `audio_url`. When user opens step 5 again (e.g. from deep link or refresh), fetch report again → get fresh `audio_url` and scores.

### 4.2 UI structure (one container)

Single wrapper (e.g. one `Card` or one `div.endReportCard`):

1. **Recording player**
   - If `report?.final_recording?.audio_url` exists: `<audio controls src={...} />` with a short label (e.g. “Your final recording”).
   - Else: show a short message: “Recording playback not available” (e.g. expired URL, or no recording).

2. **Graph**
   - Component e.g. `ReportSessionChart` that accepts `data: { warmup, final, overall }` (0–100).
   - Render a simple bar chart or 3-point chart (Warm-up, Final, Overall). Reuse styling (e.g. orange, card) from existing chart if desired; do not depend on “list of past recordings” API for this first version.

3. **Report text**
   - Existing report block: `report?.report_text` (or fallback “Report pending.”).

Then below the container: existing **progress bar** and **“Start new homework”** button.

### 4.3 When playback URL expires

- **Option A:** On step 5 mount, always fetch report (fresh URL). If user leaves the tab open for a long time and then hits play, URL might be expired; show “Playback not available” or “Link expired. Refresh the page to listen again.”
- **Option B:** If you add the optional **playback-url** endpoint, on `audio` error (or on a “Refresh playback” control), call that endpoint and set `audio.src` to the new URL. No need to refetch the whole report.

### 4.4 Graph data definition

- Backend must return **all three** scores in the report endpoint: warmup, final, overall (from `performance_score_1`, `performance_score_2`, `performance_score_end`). They exist at report time in the current implementation.
- If in the future only “overall” exists, the graph can be a single-value display (e.g. gauge or one bar) until backend exposes warmup/final again.

---

## 5. Implementation order

| # | Task | Owner |
|---|------|--------|
| 1 | Backend: Add `GET /v2/homework/session/:sessionId/report` returning report_text, scores (warmup, final, overall), final_recording { id, audio_url } with fresh signed URL. Enforce completed session and owner. | Backend |
| 2 | Backend (optional): Add `GET /v2/recordings/:id/playback-url` (or session-scoped variant) returning fresh `audio_url` for a given recording. | Backend |
| 3 | BFF: Add `GET /api/homework/session/[sessionId]/report` proxy. (And optional playback-url proxy.) | Frontend repo |
| 4 | Frontend: Add homework-client method `getReport(sessionId)` and types for report response. | Frontend |
| 5 | Frontend: Step 5 — on mount, fetch report by sessionId; store in state. Persist only sessionId (and minimal context) for “back later”; do not persist audio_url. | Frontend |
| 6 | Frontend: Build single container: (1) `<audio>` from report.final_recording.audio_url, (2) ReportSessionChart(scores), (3) report text. Handle missing audio_url with message. | Frontend |
| 7 | Backend/docs: Confirm storage CORS and Content-Type for audio; document Range support. | Backend / ops |

---

## 6. Out of scope for this plan

- **Trend graph (multiple sessions):** Not required for the “one div” panel. Can be a later enhancement with a separate “session history” or “my scores over time” API.
- **Caching report response in BFF:** Omit; keep report and playback URL generation on-demand so expiry is predictable.
- **Schema change for “final” recording:** Not required; `recording_2_id` is the contract.

---

## 7. Summary

- **Report endpoint** = single source of truth for step 5; survives refresh and return visits.
- **Fresh signed URL** on each report request (and optional playback-url for refresh).
- **Final recording** = `session.recording_2_id` (already defined).
- **One div:** player → graph → text; then progress bar and CTA.
