#!/bin/sh
# One-shot job for Railway Cron: POST the scheduled clean-up, then exit 0/1.
# (founder 2026-10-05, decisions log N48.4 Q16 A). Same shape as
# railway-learning-weekly-cron.sh: Railpack, no Dockerfile, curl from
# railpack.json aptPackages.
#
# Railway: a separate service from this repo.
#   Settings → Start Command:  sh bin/railway-retention-cleaner-cron.sh
#   Settings → Cron Schedule:  17 3 * * *   (daily, 03:17 UTC)
#
# Required variables on THIS service:
#   RETENTION_CLEANER_BACKEND_URL  public URL of the Flask app
#   RETENTION_CLEANER_SECRET       must match the web service's RETENTION_CLEANER_SECRET
# Optional:
#   RETENTION_CLEANER_MODE         dry_run (the default) or live
#
# A DRY RUN DELETES NOTHING: it counts what is due by rule, logs it and
# writes a run record (public.retention_cleaner_runs). A live request
# deletes only once RETENTION_CLEANER_LIVE is True in
# services/retention_cleaner.py, which the founder sets in a reviewed change
# after reading a dry run. Until then the backend refuses it with HTTP 409
# and this job fails loudly: set RETENTION_CLEANER_MODE=live only after that
# change has shipped. Unclaimed guests are erased by the account purge, so a
# live run erases them only while the WEB service has
# PHASE1_PURGE_EXECUTION_ENABLED=true (the purge kill switch); without it
# they stay due and the run record counts them as held.
#
# The route is DEAD BY DEFAULT: without RETENTION_CLEANER_SECRET on the web
# service it returns 503, so this cron fails loudly rather than appearing to
# work. CONFIG-FIRST (CLAUDE.md): set the secret on the web service first.

set -eu

BASE="${RETENTION_CLEANER_BACKEND_URL:-}"
BASE="${BASE%/}"
KEY="${RETENTION_CLEANER_SECRET:-}"
MODE="${RETENTION_CLEANER_MODE:-dry_run}"

if [ -z "$BASE" ] || [ -z "$KEY" ]; then
  echo "railway-retention-cleaner-cron: missing RETENTION_CLEANER_BACKEND_URL or RETENTION_CLEANER_SECRET"
  exit 1
fi

case "$MODE" in
  dry_run|live) ;;
  *)
    echo "railway-retention-cleaner-cron: RETENTION_CLEANER_MODE must be dry_run or live, not '${MODE}'"
    exit 1
    ;;
esac

echo "railway-retention-cleaner-cron: POST ${BASE}/v2/internal/retention/clean (mode=${MODE})"

code="$(curl -sS -o /tmp/retention_cleaner_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/retention/clean" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${KEY}" \
  -d "{\"mode\": \"${MODE}\"}")"

cat /tmp/retention_cleaner_body.txt
echo ""

if [ "$code" = "503" ]; then
  echo "railway-retention-cleaner-cron: HTTP 503 — RETENTION_CLEANER_SECRET is not set on the"
  echo "  WEB service. The route is dead by default; set it there too."
  exit 1
fi

if [ "$code" = "409" ]; then
  echo "railway-retention-cleaner-cron: HTTP 409 — a live run was refused:"
  echo "  RETENTION_CLEANER_LIVE is False in services/retention_cleaner.py."
  echo "  It counted as a dry run and deleted nothing. Set RETENTION_CLEANER_MODE"
  echo "  back to dry_run, or ship the founder's change first."
  exit 1
fi

if [ "$code" != "200" ]; then
  echo "railway-retention-cleaner-cron: HTTP ${code}"
  exit 1
fi

# A live run that finished with failures (a guest stopped for review, a
# recording kept) says so in its record; name it in the log.
if grep -q '"state": *"failed"' /tmp/retention_cleaner_body.txt; then
  echo "railway-retention-cleaner-cron: the run stopped early — see public.retention_cleaner_runs"
  exit 1
fi
