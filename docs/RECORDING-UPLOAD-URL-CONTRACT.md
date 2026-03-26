# Recording upload URL – backend contract

## Backend guarantees (POST `/v2/homework/session/<id>/recording-upload-url`)

- **`bucket`** – Always a **string**. Supabase storage bucket name.
- **`storage_path`** – Always a **string**. Path in the bucket for this recording (use with SDK when no signed URL).
- **`signed_url_available`** – **boolean**. `true` when `upload_url` is present (use for direct PUT); `false` when client must use Supabase SDK with `bucket` + `storage_path`. Do not treat `signed_url_available: false` as "invalid".
- **`upload_url`** – Present only when the backend obtained a signed upload URL (string). Use for Storage upload as below (**multipart** PUT — not raw `body: blob`). When absent, use `bucket` + `storage_path` with `supabase.storage.from(bucket).upload(storage_path, file)`.
- **`upload_token`** – Optional string (same JWT as the `token` query on `upload_url`). Lets clients call `supabase.storage.from(bucket).uploadToSignedUrl(storage_path, token, file)` instead of hand-rolling `fetch`.
- **Response header** `X-Upload-Url-Type: signed | path` – `signed` when a signed URL was returned; `path` when client must use SDK with `storage_path`.

## Client usage

1. **When `signed_url_available` is true**  
   Supabase Storage matches the signed upload route when the body is **multipart/form-data** (same as `@supabase/storage-js` `uploadToSignedUrl`). A plain `fetch(upload_url, { method: 'PUT', body: blob, headers: { 'Content-Type': 'audio/webm' } })` often returns **404** (`Route PUT:... not found`).

   **Option A — Supabase client (recommended):** if `response.upload_token` is set,

   `await supabase.storage.from(response.bucket).uploadToSignedUrl(response.storage_path, response.upload_token, file)`

   **Option B — `fetch`:** build `FormData`, append `cacheControl` (e.g. `'3600'`), append the file with an **empty field name** (first argument `''`), set header `x-upsert` to `'true'` or `'false'`, then `PUT` to `response.upload_url` with that body (do not set `Content-Type` manually; the browser sets the multipart boundary).

2. **When `signed_url_available` is false**  
   Use Supabase SDK: `supabase.storage.from(response.bucket).upload(response.storage_path, file)`.

3. **Single path for BFF/consumer**  
   You can normalize to one path: `path = response.storage_path` (always present). Return `{ bucket: response.bucket, storage_path: path }` downstream; use `response.upload_url` for PUT when present.

## Report playback URL

- **GET report** returns `final_recording.audio_url` and `recording.audio_url` as **string or null** only (no raw UUIDs or other types). Use them as strings for `<audio src={...}>` or playback.
