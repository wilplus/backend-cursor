# Recording upload URL – backend contract and "url is not transferrable"

## Backend guarantees (POST `/v2/homework/session/<id>/recording-upload-url`)

- **`url`** – Always a **string**. Either a signed upload URL (when available) or the `storage_path` so the client never receives `undefined` for a URL-like field.
- **`upload_url`** – Present only when the backend obtained a signed upload URL (string).
- **`storage_path`**, **`bucket`** – Strings for Supabase client upload.
- **Response header** `X-Upload-Url-Type: string` – Set when `url` is a string so you can confirm in the Network tab that this backend responded and sent a string URL.

## If you see "url is not transferrable"

1. **Use the string, not the whole response**  
   Use `response.url` (or `response.upload_url` when present) as a **string** for the upload. Do not pass the whole `response` object to `postMessage`, Workers, or any API that expects a single URL string.

2. **Check the response in Network tab**  
   Find the request to your recording-upload-url (or BFF proxy). In Response headers, look for `X-Upload-Url-Type: string`. In the JSON body, confirm `url` is a string. If you don’t see this request or this header, the call may not be reaching this backend.

3. **When `url` is not an `http` URL**  
   If `url` is the storage path (no `http`), upload with the Supabase client:  
   `supabase.storage.from(response.bucket).upload(response.url, file)`.

4. **When `url` is an `http` URL**  
   Use it for a direct PUT upload (e.g. `fetch(response.url, { method: 'PUT', body: blob })` with the headers required by the signed URL).

## Report playback URL

- **GET report** returns `final_recording.audio_url` and `recording.audio_url` as **string or null** only (no raw UUIDs or other types). Use them as strings for `<audio src={...}>` or playback.
