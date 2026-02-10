# Direct-to-storage upload (by URL) — API contract and frontend flow

This flow avoids **413 Payload Too Large** by not sending audio through the API. The client uploads audio **directly to Supabase Storage**, then calls **recording-1** or **recording-2** with a small JSON body (`storage_path` + `duration_seconds`). The backend fetches the file from storage for transcription and scoring.

---

## Backend endpoints

### 1. Mint upload target

**POST** `/v2/homework/session/<session_id>/recording-upload-url`  
Auth: required (Bearer JWT).

**Request body (JSON):**
```json
{ "recording": "1" }
```
or
```json
{ "recording": "2" }
```

**Response 200:**
```json
{
  "storage_path": "<user_id>/<session_id>/<uuid>.webm",
  "bucket": "audio_recordings"
}
```

- For `recording: "1"` the session must be in **warm_up**.
- For `recording: "2"` the session must be in **final_task_ready**.
- The backend generates **storage_path**; the client must upload to this exact path.

---

### 2. recording-1 (dual mode)

**POST** `/v2/homework/session/<session_id>/recording-1`  
Auth: required.

**Option A — Multipart (unchanged):**  
`Content-Type: multipart/form-data`, field **`audio`** = file, optional **`duration_seconds`** in form.  
Backend uploads to storage, transcribes, scores, returns `recording_id`, `performance_score_1`, `task_block`.

**Option B — By URL (direct-to-storage):**  
`Content-Type: application/json`:
```json
{
  "storage_path": "<from recording-upload-url>",
  "duration_seconds": 65.5
}
```
Backend downloads the file from storage at **storage_path**, transcribes, scores, same response as Option A.  
**storage_path** must match the pattern `{user_id}/{session_id}/{uuid}.webm` for this user and session.

---

### 3. recording-2 (dual mode)

**POST** `/v2/homework/session/<session_id>/recording-2`  
Auth: required.

**Option A — Multipart:** same as today (field **`audio`**, optional **`duration_seconds`**).

**Option B — By URL:**  
`Content-Type: application/json`:
```json
{
  "storage_path": "<from recording-upload-url>",
  "duration_seconds": 72.0
}
```

Same validation: **storage_path** must be under this user/session and end with `.webm`.

---

## Frontend flow (direct-to-storage)

1. **Get upload target**  
   `POST /v2/homework/session/<sessionId>/recording-upload-url` with body `{ "recording": "1" }` (or `"2"`).  
   Save **storage_path** and **bucket** from the response.

2. **Upload audio to Supabase Storage**  
   Use the **Supabase JS client** (browser) with your project URL and **anon key** (or service role if you expose it via a backend-only path):
   ```ts
   const { data, error } = await supabase.storage
     .from(response.bucket)
     .upload(response.storage_path, audioBlob, {
       contentType: "audio/webm",
       upsert: true,
     });
   ```
   - **CORS:** Ensure the Storage bucket allows requests from your frontend origin (Supabase Dashboard → Storage → bucket → CORS).
   - **RLS:** Storage policies must allow the authenticated user to **insert** (upload) into paths under their `user_id` (e.g. `user_id/*`).

3. **Call recording-1 or recording-2 with JSON**  
   `POST /v2/homework/session/<sessionId>/recording-1` with:
   ```json
   { "storage_path": "<from step 1>", "duration_seconds": <seconds> }
   ```
   No file in this request — only a few hundred bytes of JSON, so no 413 from BFF/proxy.

4. **Retries**  
   If the upload URL step fails (e.g. session not in the right status), show an error. If **recording-1/2** returns 400 with "storage_path invalid", the path may have expired or been wrong; re-mint with **recording-upload-url** and upload again.

---

## Design choices

- **storage_path, not arbitrary audio_url:** The backend generates the path and later fetches from that path in its own bucket. The client never sends a free-form URL.
- **Validation:** Backend checks that **storage_path** starts with `{user_id}/{session_id}/` and ends with `.webm`.
- **Download for transcription:** Backend uses **db.download_audio(bucket, path)** to load bytes from Supabase Storage, then passes them to Whisper (via BytesIO). For very large files you could add streaming/temp file later.

---

## Summary

| Step | Who | What |
|------|-----|------|
| 1 | Frontend | POST recording-upload-url → get **storage_path**, **bucket** |
| 2 | Frontend | Upload blob to Supabase Storage at **storage_path** (Supabase JS) |
| 3 | Frontend | POST recording-1 (or recording-2) with JSON **storage_path** + **duration_seconds** |
| 4 | Backend | Download from storage, transcribe, score, persist — same as multipart flow |

This removes large payloads from the API and BFF, eliminating 413 from body size limits.

---

## Risks and alignment (what’s in place vs frontend/config)

| Risk | Where | Backend / doc in place? | Notes |
|------|--------|--------------------------|--------|
| **Supabase Storage** (bucket missing, CORS, RLS) | Recording 1 & 2 | Doc only | Contract doc says: set CORS on the bucket and RLS so the user can upload to their path. Backend doesn’t create the bucket or set Storage policies; that’s Supabase Dashboard / config. |
| **Backend doesn’t implement upload-URL** | recording-upload-url | Yes | `POST /v2/homework/session/<id>/recording-upload-url` is implemented; returns 200 with `bucket` + `storage_path`. Frontend can still keep multipart as fallback if desired. |
| **Backend expects different path** | Recording 1/2 | Yes | Backend **mints** the path (upload-url) and **validates** it in recording-1/2 (`_validate_storage_path`: prefix `user_id/session_id/`, suffix `.webm`). So we accept exactly the path we gave. |
| **Session / step derivation** | Resume (step 0→1) | Contract stable | Step is derived from GET session/status (e.g. status, recording_1_id, recording_2_id). Backend keeps status enum and response shape stable; frontend owns `deriveStepFromStatus`. |
| **Single start attempt** (autoStartAttempted) | Frontend | N/A | Purely frontend; backend has no notion of “one attempt per load.” |
| **Abort during upload** (partial state) | Recording 1/2 | Not mitigated | If user aborts, Supabase upload or POST may still complete; backend doesn’t do cleanup or idempotency for orphaned files. Frontend can retry or show “upload failed” and re-mint URL. |
| **Mock vs real** (bucket name) | Dev / staging | Align mock to backend | Backend uses `AUDIO_BUCKET_NAME` = **"audio_recordings"** (config). If mock returns `bucket: "recordings"`, client uploads to a different bucket; recording-1/2 then download from **audio_recordings** and won’t find the file. Mock should return `bucket: "audio_recordings"` (or whatever the backend config is) and a path that matches `user_id/session_id/*.webm`. |
