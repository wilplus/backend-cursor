#!/bin/sh
# One-shot job for Railway Cron: POST the weekly learning job, then exit 0/1.
# (founder 2026-09-30; build plan ML-3). Same shape as railway-drift-cron.sh:
# Railpack, no Dockerfile, curl from railpack.json aptPackages.
#
# Railway: a second service from this repo.
#   Settings → Start Command:  sh bin/railway-learning-weekly-cron.sh
#   Settings → Cron Schedule:  0 6 * * 1   (Mondays 06:00 UTC)
#
# Required variables on THIS service:
#   LEARNING_WEEKLY_BACKEND_URL  public URL of the Flask app
#   LEARNING_WEEKLY_SECRET       must match the web service's LEARNING_WEEKLY_SECRET
#
# The route is DEAD BY DEFAULT: without LEARNING_WEEKLY_SECRET on the web
# service it returns 503, so this cron fails loudly rather than appearing to
# work. CONFIG-FIRST (CLAUDE.md): set the secret on the web service first.

set -eu

BASE="${LEARNING_WEEKLY_BACKEND_URL:-}"
BASE="${BASE%/}"
KEY="${LEARNING_WEEKLY_SECRET:-}"

if [ -z "$BASE" ] || [ -z "$KEY" ]; then
  echo "railway-learning-weekly-cron: missing LEARNING_WEEKLY_BACKEND_URL or LEARNING_WEEKLY_SECRET"
  exit 1
fi

echo "railway-learning-weekly-cron: POST ${BASE}/v2/internal/learning/weekly"

code="$(curl -sS -o /tmp/learning_weekly_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/learning/weekly" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${KEY}" \
  -d '{}')"

cat /tmp/learning_weekly_body.txt
echo ""

if [ "$code" = "503" ]; then
  echo "railway-learning-weekly-cron: HTTP 503 — LEARNING_WEEKLY_SECRET is not set on the"
  echo "  WEB service. The route is dead by default; set it there too."
  exit 1
fi

if [ "$code" != "200" ]; then
  echo "railway-learning-weekly-cron: HTTP ${code}"
  exit 1
fi

# A cue that cleared its bar carries a drafted migration in the body: the
# founder's go merges it (ML-14). Say so in the log so nobody misses it.
if grep -q '"ready_cues": *\[[^]]' /tmp/learning_weekly_body.txt; then
  echo "railway-learning-weekly-cron: a shadow cue is READY — see the founder's pace panel"
fi
