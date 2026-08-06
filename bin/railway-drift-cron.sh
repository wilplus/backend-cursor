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
# Railway: one cron service, same repo. THIS SCRIPT HAS NO DOCKERFILE, unlike
# the other cron scripts here — it runs on the standard build:
#   Settings → Builder:        Railpack  (the default; NOT Dockerfile)
#   Settings → Start Command:  sh bin/railway-drift-cron.sh
#   Settings → Cron Schedule:  0 6 * * 1     (06:00 UTC Mondays)
#   Variables:                 DRIFT_BACKEND_URL, DRIFT_MONITOR_SECRET
#
# ⚠️ DO NOT SET A DOCKERFILE PATH. Both ways of trying cost a debug cycle on
# 2026-08-06, and neither failure names its real cause:
#
#   path = Dockerfile.life-reminders-cron (+ this start command)
#       -> sh: can't open 'bin/railway-drift-cron.sh': No such file or directory
#          Those per-cron images copy ONE script to /app/run.sh; there is no
#          bin/ inside them. Worse, with the start command CLEARED that image's
#          ENTRYPOINT would have sent LIFE REMINDERS to real users on the drift
#          schedule — a silent wrong-payload failure instead of a loud one.
#
#   path = <empty> (+ this start command)
#       -> couldn't locate a dockerfile at path Dockerfile in code archive
#          Empty means ./Dockerfile, and this repo has no bare Dockerfile —
#          only the suffixed per-cron ones. Railway auto-detects the Dockerfile
#          builder FROM those siblings and then renders Builder as a read-only
#          card, so there is no Railpack option to pick on an existing service.
#          Creating a NEW service is what gets you Railpack (Default) back.
#
# ⚠️ AND THIS SCRIPT NEEDS curl, WHICH THE RAILPACK IMAGE DOES NOT SHIP.
#       -> bin/railway-drift-cron.sh: 45: curl: not found
# Every OTHER curl cron here (devbugs, annotation-export, life-reminders) runs
# from a curlimages/curl Dockerfile, so none of them ever needed curl in the
# app image and nobody noticed it was missing. This one runs on the standard
# build, so `curl` is listed in railpack.json's deploy.aptPackages. Keep it
# there: dropping it breaks this cron ONLY, and only at 06:00 on a Monday.
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
