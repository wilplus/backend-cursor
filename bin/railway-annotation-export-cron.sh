#!/bin/sh
# One-shot job for Railway Cron: POST internal annotation export, then exit 0/1.
#
# Railway: duplicate your backend repo as a second service (or same repo, different service).
#   Settings → Start Command:  sh bin/railway-annotation-export-cron.sh
#   Settings → Cron Schedule:  0 6 * * *   (daily 06:00 UTC — adjust as needed)
#
# Required variables (same project as web, or set explicitly):
#   ANNOTATION_EXPORT_BACKEND_URL  public URL of the Flask app, e.g. https://xxx.up.railway.app
#   ANNOTATION_EXPORT_CRON_SECRET  must match the web service ANNOTATION_EXPORT_CRON_SECRET
#
# Optional:
#   ANNOTATION_EXPORT_LIMIT  default 20000

set -eu

BASE="${ANNOTATION_EXPORT_BACKEND_URL%/}"
SECRET="${ANNOTATION_EXPORT_CRON_SECRET:-}"
LIMIT="${ANNOTATION_EXPORT_LIMIT:-20000}"

if [ -z "$BASE" ] || [ -z "$SECRET" ]; then
  echo "railway-annotation-export-cron: missing ANNOTATION_EXPORT_BACKEND_URL or ANNOTATION_EXPORT_CRON_SECRET"
  exit 1
fi

echo "railway-annotation-export-cron: POST ${BASE}/v2/internal/annotation-export limit=${LIMIT}"

code="$(curl -sS -o /tmp/ann_export_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/annotation-export" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${SECRET}" \
  -d "{\"limit\":${LIMIT}}")"

cat /tmp/ann_export_body.txt
echo ""

if [ "$code" != "200" ]; then
  echo "railway-annotation-export-cron: HTTP ${code}"
  exit 1
fi

echo "railway-annotation-export-cron: ok"
exit 0
