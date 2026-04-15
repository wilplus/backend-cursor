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
