# Coach / reference videos on Cloudflare R2

When **`R2_ACCOUNT_ID`**, **`R2_ACCESS_KEY_ID`**, and **`R2_SECRET_ACCESS_KEY`** are set, the backend uses **R2 (S3 API)** for coach feedback and Training Studio reference video bytes. Supabase remains DB + Auth.

Set **`COACH_FEEDBACK_VIDEO_BUCKET`** (and optionally **`R2_BUCKET_NAME`**) to your R2 bucket id, e.g. `coach-feedback-videos`.

Optional **`R2_PUBLIC_BASE_URL`**: HTTPS base (no trailing slash) for a **public bucket or custom domain**, e.g. `https://videos.example.com`. If set, `source_video_url` and `file_url` from `upload-url` use stable URLs for `<video src>`.

## R2 bucket CORS (Dashboard → R2 → bucket → Settings → CORS)

Allow your Next.js origins to **PUT** (presigned upload) and **GET** (playback if public or via signed URL from your domain). Example:

```json
[
  {
    "AllowedOrigins": [
      "https://app.willonski.com",
      "http://localhost:3000"
    ],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag", "Content-Length"],
    "MaxAgeSeconds": 3600
  }
]
```

Adjust origins for your admin / Training Studio host.

## Flow: mint URL → PUT raw file → register

1. **POST** `/v2/admin/copilot/reference-videos/upload-url`
   - Request JSON:
     - `filename` (required)
     - `file_size_bytes` (optional)
     - `content_type` (optional, codec suffix is stripped)
     - `storage_provider` (`"r2"`, optional; defaults to `r2`)
   - Response `200` JSON:
     - `upload_url`
     - `storage_path`
     - `content_type` (exact value used for signature; use this on PUT)
     - `bucket`
2. **Browser upload**: `PUT upload_url` with raw file bytes and header `Content-Type: <response.content_type>`.
   - **Do not use `FormData` / multipart**.
3. **POST** `/v2/admin/copilot/reference-videos/register-from-storage`
   - Request JSON:
     - `storage_path` (required), `storage_provider: "r2"`, `bucket` (optional)
     - optional: `session_id`, `user_id`, `draft_id`, `title`, `reference_tags`, `is_universal_video`, `track_progress`
   - Response `202` JSON:
     - `job_id`
     - `poll_url`
     - `message`
4. **GET** `/v2/admin/copilot/reference-videos/upload-jobs/<job_id>` until:
   - `job.stage = "completed"` (includes `reference_video`, optional `preview_url`)
   - or `job.stage = "failed"` (includes `error` / `message`)

Draft attach uses **`r2://bucket/key`** in `full_override_video_storage_path` when the reference row is R2-backed; homework resolution and pipeline fetch support that URI.

## Env summary

| Variable                      | Purpose                                             |
| ----------------------------- | --------------------------------------------------- |
| `R2_ACCOUNT_ID`               | Cloudflare account id (subdomain in S3 endpoint)    |
| `R2_ACCESS_KEY_ID`            | R2 API token access key                             |
| `R2_SECRET_ACCESS_KEY`        | R2 API token secret                                 |
| `R2_BUCKET_NAME`              | Optional; defaults to `COACH_FEEDBACK_VIDEO_BUCKET` |
| `COACH_FEEDBACK_VIDEO_BUCKET` | Bucket name in R2 (e.g. `coach-feedback-videos`)    |
| `R2_PUBLIC_BASE_URL`          | Optional stable HTTPS base for public objects       |

If R2 vars are **unset**, behavior falls back to **Supabase Storage** as before.
