#!/bin/sh
# One-shot job for Railway Cron: POST the deletion completion run, then exit
# 0/1 (founder 2026-10-05, decisions log N48.4 Q14 A, Q17 A; migration 0422).
# Same shape as railway-learning-weekly-cron.sh: Railpack, no Dockerfile,
# curl from railpack.json aptPackages.
#
# Railway: a service from this repo.
#   Settings → Start Command:  sh bin/railway-deletion-completion-cron.sh
#   Settings → Cron Schedule:  37 * * * *   (hourly; a run is idempotent)
#
# Required variables on THIS service:
#   DELETION_COMPLETION_BACKEND_URL  public URL of the Flask app
#   DELETION_COMPLETION_SECRET       must match the web service's
#                                    DELETION_COMPLETION_SECRET
#
# On the WEB service:
#   DELETION_COMPLETION_SECRET       without it the route answers 503
#   PHASE1_PURGE_EXECUTION_ENABLED   "true" to delete; anything else makes
#                                    every run a dry run that only reports
#                                    what is due (read the dry run first)
#
# The route is DEAD BY DEFAULT: without DELETION_COMPLETION_SECRET on the web
# service it returns 503, so this cron fails loudly rather than appearing to
# work. CONFIG-FIRST (CLAUDE.md): set the secret on the web service first.

set -eu

BASE="${DELETION_COMPLETION_BACKEND_URL:-}"
BASE="${BASE%/}"
KEY="${DELETION_COMPLETION_SECRET:-}"

if [ -z "$BASE" ] || [ -z "$KEY" ]; then
  echo "railway-deletion-completion-cron: missing DELETION_COMPLETION_BACKEND_URL or DELETION_COMPLETION_SECRET"
  exit 1
fi

echo "railway-deletion-completion-cron: POST ${BASE}/v2/internal/deletion/complete-due"

code="$(curl -sS --max-time 900 -o /tmp/deletion_completion_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/deletion/complete-due" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${KEY}" \
  -d '{}')"

cat /tmp/deletion_completion_body.txt
echo ""

if [ "$code" = "503" ]; then
  echo "railway-deletion-completion-cron: HTTP 503 — DELETION_COMPLETION_SECRET is not set on the"
  echo "  WEB service. The route is dead by default; set it there too."
  exit 1
fi

if [ "$code" != "200" ]; then
  echo "railway-deletion-completion-cron: HTTP ${code}"
  exit 1
fi

# A dry run deletes nothing: say so, so nobody reads it as done.
if grep -q '"mode": *"dry_run"' /tmp/deletion_completion_body.txt; then
  echo "railway-deletion-completion-cron: DRY RUN — PHASE1_PURGE_EXECUTION_ENABLED is not \"true\" on the web service"
fi

# A purge that met rows no rule decides waits for a person (GET /v2/admin/deletions).
if grep -q '"left_for_a_person": *\[[^]]' /tmp/deletion_completion_body.txt; then
  echo "railway-deletion-completion-cron: a deletion waits for a person — see /v2/admin/deletions"
fi
