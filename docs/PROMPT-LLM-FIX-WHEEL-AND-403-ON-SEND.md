# Prompt for LLM: Fix 403 on "Send" and wheel not updating (homework step 1)

Use this when debugging the homework flow where (1) the strength/pace wheel does not update in real time, and (2) after clicking "Send" to submit the first recording, the user sees **403** with **"new row violates row-level security policy"**.

---

## Context

- **App:** Willab homework flow. Step 1 = Warm-up task (e.g. "How was your day so far?") with a real-time **strength/pace wheel** (Strength in dB, Pace in WPM). User records, then clicks **Send** to submit recording-1.
- **Flow (intended):**
  1. Frontend gets upload URL: **POST** `/api/homework/session/<sessionId>/recording-upload-url` with `{ "recording": "1" }` → backend returns `storage_path` and `bucket`.
  2. Frontend uploads the **audio blob** to **Supabase Storage** at that path (e.g. `supabase.storage.from(bucket).upload(storage_path, blob, ...)`).
  3. Frontend calls **POST** `/api/homework/session/<sessionId>/recording-1` with JSON `{ "storage_path": "...", "duration_seconds": ... }` (or multipart with the file). Backend then downloads from Storage (or uses the file), transcribes, generates `context_short`, `performance_score_1`, and moves the session to step 2 (task block).
- **Observed:** Red banner "new row violates row-level security policy"; in Network tab a **fetch** to **Supabase Storage** fails (e.g. `*.supabase.co/storage/v1/object/audio_recordings/...`) with **403 Unauthorized** and that message.

---

## What is likely happening

1. **403 on Send**  
   The failing request in the Network tab is to **Supabase Storage** (the `audio_recordings` bucket), not to the Flask backend. So the **403 "new row violates row-level security policy"** is coming from **Storage RLS**: the browser (or the frontend using the Supabase JS client with the user's JWT) is trying to **upload** (INSERT) an object to the bucket, and the bucket's **Storage RLS policy** is blocking that upload. Common causes:
   - No **INSERT** policy on the bucket for the authenticated user, or the policy does not allow the path being used (e.g. path must be `auth.uid()/*` and the path does not match).
   - Backend returns `storage_path` like `{user_id}/{session_id}/{uuid}.webm`. The frontend must upload to that exact path using a Supabase client that sends the **user's JWT** so `auth.uid()` equals that `user_id`. If the frontend uploads with a different key (e.g. service role from a backend) or the path doesn't match the policy, RLS blocks with 403.

2. **Wheel not updating**  
   The real-time wheel is driven by **recording-metrics-chunk**: the frontend sends PCM chunks to **POST** `/api/homework/session/<sessionId>/recording-metrics-chunk` and gets back `{ voiced_ratio, pause_score }` (or similar) and updates the wheel. If the wheel does not move:
   - **Mic not allowed:** Browser may have blocked microphone access; no PCM is sent, so no metrics and wheel stays default (-160 dB, ~60 WPM).
   - **Chunks not sent:** The PCM pipeline might not be started on step 1, or might be torn down (e.g. after a re-render or step change). Check Network tab for repeated requests to `recording-metrics-chunk` and their status (200 vs 403/404).
   - **Chunks sent, UI not updated:** If `recording-metrics-chunk` returns 200 but the wheel doesn't move, the bug is in the frontend code that maps chunk responses to the wheel state (e.g. state not set, or wrong component instance).

3. **User's theory ("no score/context → DB error")**  
   Score and context are generated **on the backend** only **after** a successful recording-1 (backend has the file or storage_path and transcribes it). So if the **upload to Storage** fails with 403, the frontend may never get to call recording-1 with a valid path, or the backend would not have the file. The 403 the user sees is from **Storage** at upload time, not from a missing score/context in the DB. Fixing Storage RLS so the upload succeeds is the first step; then the backend can process the recording and write score/context (backend uses service role, so table RLS is not the cause of this 403).

---

## What to do (checklist for the other LLM)

1. **Confirm which request returns 403**  
   In Network tab, find the failed request. If the URL is `*.supabase.co/storage/v1/object/audio_recordings/...`, it is **Storage** (upload or read). If it is `*/recording-metrics-chunk`, it is the chunk endpoint (BFF/backend). The message "new row violates row-level security policy" usually means an **insert** was blocked by RLS — for Storage that’s the **upload** (object insert).

2. **Fix Storage upload (403 on Send)**  
   - In **Supabase Dashboard** → **Storage** → bucket `audio_recordings` (or the one your backend uses) → **Policies**.  
   - Add or fix an **INSERT** (upload) policy so that the authenticated user (JWT `auth.uid()`) can upload objects whose path starts with their user id (e.g. `auth.uid()::text || '/%'` or equivalent). Backend path format is `{user_id}/{session_id}/{uuid}.webm`.  
   - Ensure the frontend uploads with the **Supabase client** that has the **user’s session** (e.g. `supabase.auth.getSession()` then use that client so the request is authenticated as that user).  
   - See backend repo docs: `HOMEWORK-DIRECT-UPLOAD-SETUP.md` (Storage RLS and CORS).

3. **Fix wheel not updating**  
   - Check **browser mic permission** for the site (no prompt or "blocked" → no PCM).  
   - In Network tab, on step 1 (Warm-up), see if there are repeated **recording-metrics-chunk** requests and whether they return **200** or 4xx. If 403, the BFF might be doing a Supabase write (see `DEBUG-403-RECORDING-METRICS-CHUNK-RLS.md`). If 200 but wheel static, the bug is in the frontend code that updates the wheel from chunk responses (or the pipeline is not running for that step).  
   - Ensure the PCM chunk pipeline is **started** when the Warm-up step is shown and **not** torn down until the user leaves the step or submits.

4. **Order of fixes**  
   Fix **Storage RLS** first so "Send" succeeds and recording-1 can complete. Then debug the wheel (mic, chunk requests, UI update) separately so the user gets real-time feedback and a successful upload.

---

## Backend references (this repo)

- **Storage / direct upload:** `docs/HOMEWORK-DIRECT-UPLOAD-SETUP.md`  
- **403 on recording-metrics-chunk (RLS):** `docs/DEBUG-403-RECORDING-METRICS-CHUNK-RLS.md`  
- **Session status as source of truth:** `docs/ROOT-CAUSE-SESSION-STATUS-MISMATCH.md`

No backend (Flask) change is required for the 403 on Send; the fix is **Supabase Storage RLS** (and possibly frontend auth when uploading). The wheel is frontend + BFF (chunk endpoint); backend only returns metrics when chunks are posted to it.
