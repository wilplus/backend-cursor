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
| Home-screen / tab icons | `static/dev_bugs_icons/` (regen: `scripts/gen_dev_bugs_icons.mjs`) |
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
- `GET  /dev-bugs/icons/<file>` → the home-screen / favicon PNGs (un-gated,
  allowlisted filenames only, cached 7 days).
- `GET  /dev-bugs/manifest.webmanifest` → PWA manifest. `start_url` follows the
  Host: `/` on the dev subdomain, `/dev-bugs` anywhere else, so an install from
  either mount lands back on the page instead of the API health payload.

## Home-screen icon

Add-to-Home-Screen installs as **“Willab dev”**: the Willab three-dot mark
(small · large · small, black on white) plus a small **dev** label, so it sits
next to the real app icon without being mistaken for it.

**Icon-only, by founder call (2026-07-26)** — the page itself carries no logo.
`DevBugsPageTests.test_page_carries_no_logo` holds that line.

Assets live in `static/dev_bugs_icons/` and are committed. The mark is drawn as
vector circles (no webfont, no traced raster), so it stays crisp at every size.
Regenerate only when the mark changes:

```bash
node scripts/gen_dev_bugs_icons.mjs     # needs node + playwright (chromium)
```

| File | Consumer |
|---|---|
| `icon-180.png` | `apple-touch-icon` — iOS Add to Home Screen |
| `icon-192.png`, `icon-512.png` | manifest / Android install |
| `icon-maskable-512.png` | manifest `purpose=maskable` (Android safe zone) |
| `favicon-32.png`, `favicon-180.png` | browser tab / bookmark — bare mark, no `dev` label (it rasterizes to mush at 32 px; the tab title already reads `dev-bugs`) |

iOS ignores `data:` URIs for `apple-touch-icon`, which is why these are real
files behind a route rather than inlined in the page. If the icon doesn't change
on your phone, delete the old home-screen shortcut and re-add it — iOS caches the
icon per shortcut, not per page load.

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
- Test: `venv/bin/python -m unittest test_dev_bugs` (36 tests — routes, digest
  service, the served page's guards, and the icon assets/routes).
