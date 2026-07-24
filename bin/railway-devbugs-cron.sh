#!/bin/sh
# One-shot job for Railway Cron: POST the dev-bugs digest, then exit 0/1.
#
# Emails all OPEN dev-bugs to DEV_BUGS_TO as an LLM-ready triage prompt (images
# attached) and marks them shipped — the SAME routine the "Send now" button runs.
# With 0 open bugs it is a no-op (no empty email).
#
# Railway: duplicate your backend repo as a second service (or same repo,
# different service). Two ways to run it:
#   A) Settings → Start Command:  sh bin/railway-devbugs-cron.sh
#   B) Settings → Builder: Dockerfile, Dockerfile path: Dockerfile.devbugs-cron
#   Settings → Cron Schedule:  0 9 */3 * *   (09:00 UTC every 3rd day)
#
# Required variables (same project as web, or set explicitly):
#   DEV_BUGS_BACKEND_URL  public URL of the Flask app, e.g. https://dev.willpowerlab.com
#   DEV_BUGS_KEY          must match the web service DEV_BUGS_KEY

set -eu

BASE="${DEV_BUGS_BACKEND_URL%/}"
KEY="${DEV_BUGS_KEY:-}"

if [ -z "$BASE" ] || [ -z "$KEY" ]; then
  echo "railway-devbugs-cron: missing DEV_BUGS_BACKEND_URL or DEV_BUGS_KEY"
  exit 1
fi

echo "railway-devbugs-cron: POST ${BASE}/api/dev-bugs/send"

code="$(curl -sS -o /tmp/devbugs_body.txt -w "%{http_code}" -X POST \
  "${BASE}/api/dev-bugs/send" \
  -H "Content-Type: application/json" \
  -H "x-dev-key: ${KEY}" \
  -d '{}')"

cat /tmp/devbugs_body.txt
echo ""

if [ "$code" != "200" ]; then
  echo "railway-devbugs-cron: HTTP ${code}"
  exit 1
fi

echo "railway-devbugs-cron: ok"
exit 0
