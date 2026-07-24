# dev-bugs — internal bug collector (setup & ops)

A tiny founder-only tool at **`dev.willpowerlab.com`**: jot bugs (text, voice, or
image) from phone or PC, stored in the existing Supabase DB. A Railway cron
emails all `open` bugs to `artur@willonski.com` every 3 days as a ready-to-paste
LLM triage prompt (images attached), then marks them `shipped`. A **Send now**
button runs the same thing on demand. Shipped bugs stay as read-only history.

Built on the existing stack — Flask blueprint, Supabase `db.client`, Resend
mailer, the annotation-cron curl pattern. No new frameworks or providers.

## Files

| Piece | File |
|---|---|
| Table | `migrations/add_dev_bugs.sql` |
| API + page routes | `routes/dev_bugs.py` (registered in `app.py`) |
| DB + digest/send logic | `services/dev_bugs.py` |
| Mailer attachments | `services/email_service.py` (`send_email_resend(..., attachments=)`) |
| Frontend (single file) | `static/dev_bugs.html` |
| Cron (curl endpoint) | `bin/railway-devbugs-cron.sh` + `Dockerfile.devbugs-cron` |
| Cron (standalone alt) | `scripts/send_dev_bugs.py` |
| Config | `config.py` → `DEV_BUGS_KEY`, `DEV_BUGS_TO`, `DEV_BUGS_HOST` |
| Tests | `test_dev_bugs.py` |

## API (all `/api/*` require header `x-dev-key: <DEV_BUGS_KEY>`)

- `GET  /api/dev-bugs` → `{ "open": [ {id, text, image, created_at, ...} ], "shipped": [...] }`
- `POST /api/dev-bugs` body `{ "text": string, "image": string|null }` → `201 {id}`
- `DELETE /api/dev-bugs/:id` → `204` (only while `status='open'`)
- `POST /api/dev-bugs/send` → `{ "sent": <count> }` (same routine as the cron)
- `GET  /dev-bugs` and `/` on the dev host → serves the page (un-gated; the page
  prompts for the key, the API enforces it). `image` is a URL or a `data:` URL.

## Deploy checklist

1. **Migration** — paste `migrations/add_dev_bugs.sql` into Supabase → SQL Editor → Run.
   (Or `DATABASE_URL=... python run_migration.py` after pointing its `migration_name` at `add_dev_bugs`.)
2. **Web service env** (the existing Flask service):
   - `DEV_BUGS_KEY` = a long random string (e.g. `openssl rand -hex 24`).
   - `SEND_EMAILS=true` and `RESEND_API_KEY` — required for mail to actually send.
     (If `SEND_EMAILS` is off, `/send` returns **503** and bugs stay `open`, by design — nothing is silently lost.)
   - Optional: `DEV_BUGS_TO` (defaults to `ADMIN_EMAIL` = `artur@willonski.com`), `DEV_BUGS_HOST` (defaults to `dev.willpowerlab.com`).
3. **Subdomain** — add `dev.willpowerlab.com` as a **custom domain on the existing web service** (Railway → service → Settings → Domains). Same-origin means the page and its `/api/dev-bugs` API share a host, so `API_BASE=""` works and no CORS is needed. (`x-dev-key` is also in the CORS allow-list for the cross-origin case.)
4. **Cron (every 3 days)** — add a **second Railway service** on the same repo:
   - **Option A (curl, recommended):** Start Command `sh bin/railway-devbugs-cron.sh` *(or Builder=Dockerfile, path `Dockerfile.devbugs-cron`)*. Env: `DEV_BUGS_BACKEND_URL=https://dev.willpowerlab.com` + the same `DEV_BUGS_KEY`.
   - **Option B (standalone):** Start Command `python3 scripts/send_dev_bugs.py`. Env: the app env (`SUPABASE_*`, `RESEND_API_KEY`, `SEND_EMAILS=true`, `DEV_BUGS_TO`).
   - **Cron Schedule:** `0 9 */3 * *` (09:00 UTC every 3rd day). Adjust to taste.

## Notes

- Images: the frontend compresses to JPEG (~≤200 KB) and posts a `data:` URL; we
  store it directly in `image_url` (no object storage needed). The global request
  cap is already 500 MB, so no per-route body-limit bump was necessary.
- `0` open bugs → `/send` is a no-op (no empty email).
- Test: `venv/bin/python -m unittest test_dev_bugs` (16 tests).
