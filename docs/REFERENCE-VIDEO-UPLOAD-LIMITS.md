# Reference video uploads (500 MB stack)

`POST /v2/admin/copilot/reference-videos/upload` accepts multipart form data with field **`video_file`**. The Flask app enforces a configurable cap via **`MAX_REFERENCE_VIDEO_SIZE_MB`** (default **500**). Align every layer in front of the app so requests are not rejected with **413** before they reach Flask.

## Application (Flask)

- **`app.config["MAX_CONTENT_LENGTH"]`** = `max(MAX_AUDIO_SIZE_MB, MAX_REFERENCE_VIDEO_SIZE_MB)` in megabytes (see `app.py`).
- Env: **`MAX_REFERENCE_VIDEO_SIZE_MB`** (default `500`).
- Intentional oversize returns JSON `413` with `code: PAYLOAD_TOO_LARGE` and a message referencing the configured MB cap.

## Application server (Gunicorn)

This repo runs Gunicorn via `bin/railway-web.sh` / `Procfile`.

- **`GUNICORN_TIMEOUT`**: worker silent timeout in seconds (default **1800** = 30 minutes). Large or slow uploads can exceed the old 120s default.
- Example Railway env: `GUNICORN_TIMEOUT=1800`

If you run Gunicorn manually:

```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 2 --timeout 1800
```

## Reverse proxy (required if not hitting Flask directly)

Set body size **≥ 550 MB** for headroom and long timeouts (15–30 minutes).

### Nginx

```nginx
client_max_body_size 550m;
proxy_read_timeout 1800s;
proxy_send_timeout 1800s;
send_timeout 1800s;
```

Apply inside `http`, `server`, or `location` that proxies to the API.

### Caddy

```caddyfile
reverse_proxy localhost:5000 {
    header_up X-Forwarded-For {remote_host}
    transport http {
        read_timeout 30m
        write_timeout 30m
    }
}
# Request body limits: use `request_body` max_size in Caddy 2.6+ or handle at app; prefer app + upstream docs.
```

### Traefik

Use middleware / entrypoint timeouts and body limits per your Traefik version (e.g. `buffering.maxRequestBodyBytes` or ingress annotations on Kubernetes).

### Hosted platforms (e.g. Railway)

Confirm the platform’s **maximum HTTP request body** and timeouts. If the platform caps below ~550 MB, uploads will **413** regardless of Flask settings—increase the platform limit or upload via **signed URL direct-to-storage** (separate feature).

## CORS (Next.js admin → API)

- Set **`CORS_ORIGINS`** to include the admin origin (e.g. `https://app.willonski.com`).
- `app.py` allows **`Authorization`**, **`Content-Type`**, **`X-Internal-Secret`** and standard methods including **`POST`** for preflight.

## Auth

Unchanged: admin JWT **`Authorization: Bearer <token>`** on the upload route.

## Storage / database

No API contract change: file bytes go to Supabase Storage; metadata row supports large files (size in `feature_metadata` only; path is a string).

**Supabase bucket limit:** In Dashboard → Storage → your bucket (`COACH_FEEDBACK_VIDEO_BUCKET`, default `coach_feedback_videos`) → **file size limit** must be ≥ your largest reference file (and ≥ `MAX_REFERENCE_VIDEO_SIZE_MB`). If Storage rejects the upload, the API may return **`413`** with a message mentioning **object exceeded the maximum allowed size** — that is **Supabase**, not Railway.

## What usually breaks (not “duplication”)

- **Duplicate uploads** are not the model here: each file gets a **new storage path** (`…/uuid.ext`), so Postgres is not deduplicating your file away.
- **Transcription (Whisper/ffmpeg)** runs **after** the file is in Storage and the **`admin_uploaded_reference_videos`** row exists. Before Whisper, backend extracts a compact mono 16k MP3 via ffmpeg for video/common containers (and large files) to stay under OpenAI's ~25MB request limit. If transcription fails, the row still shows **`transcription_status: failed`** and the video remains in the bucket.
- If extracted audio is still too large (over ~24MB), backend does **not** call Whisper and stores a controlled error (`file too long for transcription; trim or split`).
- **Railway:** There is **no small hard body cap** like 50MB on the platform; a **~15 minute** request timeout applies. Huge uploads that run longer can fail with a timeout (often seen as network / `502` / closed connection), not a JSON `PAYLOAD_TOO_LARGE` from Flask.
- **Flask / Gunicorn:** `MAX_CONTENT_LENGTH` and **`GUNICORN_TIMEOUT`** (see above). Oversize vs app config → **`413`** + `PAYLOAD_TOO_LARGE` from this API.
- **Next.js admin BFF:** If the browser sends the **multipart file through** a Route Handler / Server Action on **Vercel** (or similar), the **hosting provider’s serverless body limit** may reject large bodies **before** Railway. Prefer **`POST /v2/admin/copilot/reference-videos/upload-url`** (signed URL) → **browser PUT directly to Supabase** → **`POST .../register-from-storage`** so the heavy bytes **never** pass through Next or Flask.

API responses for failed synchronous uploads now include a detailed **`error`** string (admin-only routes) so you can see Storage vs DB vs other failures in the Network tab.
