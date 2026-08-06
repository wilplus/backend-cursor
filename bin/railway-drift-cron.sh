#!/bin/sh
# One-shot job for Railway Cron: POST the weekly drift run, then exit 0/1.
# Cloned from bin/railway-life-reminders-cron.sh (the house HTTP-poker pattern).
#
# Fires POST /v2/internal/drift/run with the X-Internal-Secret header. The
# backend computes PSI + the p-chart over dimension_evaluations and returns the
# PM-3 2x2 per dimension (Appendix G.5/G.7).
#
# IDEMPOTENT. The run only reads, except for minting the frozen reference the
# first time there is enough data — and reference_distribution blocks UPDATE by
# trigger, so a double-fired cron cannot overwrite a baseline.
#
# ITS OWN VARIABLES, deliberately. An earlier draft reused LIFE_BACKEND_URL
# because it holds the right value; the value is fine and the NAME is not.
# A drift cron that silently depends on a life-panel variable breaks the day
# someone retires that feature, and nothing would explain why.
#
# Railway: one cron service, same repo. Cron Schedule 0 6 * * 1 (Mondays
# 06:00 UTC). Two ways to run it, and you must pick EXACTLY ONE:
#   A) Builder Railpack (no Dockerfile path) + Start Command:
#          sh bin/railway-drift-cron.sh
#   B) Builder Dockerfile, path Dockerfile.drift-cron, NO start command
#      (that image's ENTRYPOINT already runs this script).
#
# ⚠️ SETTING BOTH IS THE FAILURE THAT ACTUALLY HAPPENED. Dockerfile.drift-cron
# contains exactly one file, /app/run.sh, and no bin/ directory — so a start
# command of `sh bin/railway-drift-cron.sh` on top of it dies with
#     sh: can't open 'bin/railway-drift-cron.sh': No such file or directory
# Clearing the Dockerfile path does NOT rescue option A on its own, either:
# Railway auto-detects the Dockerfile builder from this repo's Dockerfile.*
# siblings, an empty path resolves to ./Dockerfile, which does not exist, and
# the BUILD fails with "couldn't locate a dockerfile at path Dockerfile".
# For option A the Builder dropdown itself has to say Railpack.
#
# And never point this service at Dockerfile.life-reminders-cron: with the
# start command cleared, its ENTRYPOINT would send LIFE REMINDERS to real
# users on the drift schedule.
#
# Required variables:
#   DRIFT_BACKEND_URL     public URL of the Flask app, e.g. https://dev.willpowerlab.com
#   DRIFT_MONITOR_SECRET  must match the WEB service's DRIFT_MONITOR_SECRET
# Optional:
#   DRIFT_WEEKS           lookback window, default 4 (the appendix's figure)
#
# The route is DEAD BY DEFAULT: without DRIFT_MONITOR_SECRET on the web service
# it returns 503, so this cron fails loudly rather than appearing to work.

set -eu

BASE="${DRIFT_BACKEND_URL:-}"
BASE="${BASE%/}"
KEY="${DRIFT_MONITOR_SECRET:-}"
WEEKS="${DRIFT_WEEKS:-4}"

if [ -z "$BASE" ] || [ -z "$KEY" ]; then
  echo "railway-drift-cron: missing DRIFT_BACKEND_URL or DRIFT_MONITOR_SECRET"
  exit 1
fi

echo "railway-drift-cron: POST ${BASE}/v2/internal/drift/run?weeks=${WEEKS}"

code="$(curl -sS -o /tmp/drift_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/drift/run?weeks=${WEEKS}" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${KEY}" \
  -d '{}')"

cat /tmp/drift_body.txt
echo ""

if [ "$code" = "503" ]; then
  echo "railway-drift-cron: HTTP 503 — DRIFT_MONITOR_SECRET is not set on the"
  echo "  WEB service. The route is dead by default; set it there too."
  exit 1
fi

if [ "$code" != "200" ]; then
  echo "railway-drift-cron: HTTP ${code}"
  exit 1
fi

# `worst` is the one field an alert should key on. PIPELINE_CHANGED is the one
# worth waking up for: stable inputs with drifting decisions means OUR OWN code
# moved, which is the failure the whole layer exists to catch.
if grep -q '"worst": *"PIPELINE_CHANGED"' /tmp/drift_body.txt; then
  echo "railway-drift-cron: PIPELINE_CHANGED — triage this first (PM-3)"
fi

echo "railway-drift-cron: ok"
exit 0
