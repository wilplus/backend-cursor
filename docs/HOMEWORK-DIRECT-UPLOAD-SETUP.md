# Homework direct-to-storage upload — what you need to do

This checklist covers everything that is **not** implemented in the backend and must be done in **Supabase**, **BFF**, or **frontend** for the direct-to-storage flow to work and stay reliable.

---

## 1. Supabase Storage (bucket, CORS, RLS)

The backend returns a **bucket** name (e.g. `audio_recordings`) and a **storage_path**. The **browser** uploads the audio blob directly to Supabase Storage. For that to work:

### 1.1 Bucket exists

- In **Supabase Dashboard** → **Storage**: ensure the bucket used by the backend exists.
- Backend uses **`AUDIO_BUCKET_NAME`** from config (default **`audio_recordings`**). Create that bucket if it doesn’t exist.

### 1.2 CORS for the bucket

- In **Supabase Dashboard** → **Storage** → your bucket (e.g. `audio_recordings`) → **Policies / CORS** (or project **Settings** → **API** if CORS is global).
- Allow your **frontend origin** (e.g. `https://app.willonski.com`, `http://localhost:3000`) for **PUT** and **POST** (and **GET** if you need to read back).
- Without this, the browser will block the upload and you’ll see a CORS error in the console.

### 1.3 RLS (Storage policies)

- The frontend uploads using the **Supabase JS client** (anon key or service role). Storage uses **RLS**.
- Add a policy that allows **INSERT** (upload) for paths that match your pattern. For example:
  - **Policy:** Allow authenticated users to upload to objects under `{user_id}/*` (where `user_id` is the JWT `sub` or a claim you use).
- Backend path format is `{user_id}/{session_id}/{uuid}.webm`. So a policy like “allow upload if object name starts with `auth.uid()` (or the user’s id)” is typical.
- If RLS blocks the upload, Supabase returns **401/403** and the frontend will see “Upload failed”.

---

## 2. BFF (Next.js API route)

- The browser calls something like **POST** `/api/homework/session/<sessionId>/recording-upload-url`.
- You must have a **BFF route** that:
  - Accepts **POST** with body `{ "recording": "1" }` or `"2"`.
  - Forwards to **POST** `{BACKEND_URL}/v2/homework/session/<sessionId>/recording-upload-url` with the same body and **Authorization** (and any other headers the backend needs).
  - Returns the backend response (status + JSON).
- **File path (App Router):** e.g. `app/api/homework/session/[sessionId]/recording-upload-url/route.ts` and export **POST**.
- If this route is missing or the path is wrong, the browser gets **404** (from Next.js).

---

## 3. Frontend

### 3.1 Mock bucket name (dev / staging)

- If you use **useMockHomework()** or a mock for `recording-upload-url`, the mock must return the **same bucket** the backend uses: **`audio_recordings`** (or whatever `AUDIO_BUCKET_NAME` is in your backend config).
- If the mock returns `bucket: "recordings"`, the client uploads to a different bucket and the backend (which downloads from `audio_recordings`) won’t find the file → “storage_path invalid” or missing file.

### 3.2 Optional: multipart fallback

- If **recording-upload-url** or the Supabase upload fails, you can fall back to the **multipart** flow: **POST** recording-1/2 with **FormData** and the **audio** file. The backend still supports that.
- This avoids “homework flow not available” when only the direct-to-storage path is broken (e.g. RLS not set yet).

### 3.3 Retry / abort

- Backend is **idempotent** for the by-URL flow: if you **POST** recording-1 or recording-2 again with the **same** `storage_path` and the session already has that recording, the backend returns **200** with the same payload (no duplicate row).
- So the frontend can **retry** after a failure or after the user re-triggers submit without creating duplicates.

---

## 4. Backend deployment

- Ensure the **deployed** Flask app includes the **recording-upload-url** route and the **by-URL** handling for recording-1 and recording-2. If the live app is an old build, you’ll get **404** or “audio required” when calling with JSON only.

---

## Quick checklist

| Done | Item |
|------|------|
| ☐ | Supabase bucket **audio_recordings** (or your `AUDIO_BUCKET_NAME`) exists |
| ☐ | CORS on that bucket allows your frontend origin (PUT/POST) |
| ☐ | Storage RLS allows upload (e.g. INSERT) for paths like `{user_id}/*` |
| ☐ | BFF route **POST** `.../recording-upload-url` exists and proxies to backend |
| ☐ | Mock (if used) returns **bucket: "audio_recordings"** and path like `user_id/session_id/*.webm` |
| ☐ | Backend redeployed with recording-upload-url and by-URL recording-1/2 |
| ☐ | (Optional) Frontend falls back to multipart if upload-URL or Supabase upload fails |

Once these are done, the direct-to-storage flow should work and 404/CORS/RLS issues should be resolved.
