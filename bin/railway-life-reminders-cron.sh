#!/bin/sh
# One-shot job for Railway Cron: POST one life-reminder slot, then exit 0/1.
# Cloned from bin/railway-devbugs-cron.sh (the house HTTP-poker pattern).
#
# Fires POST /v2/internal/life/reminders?slot=$LIFE_REMINDER_SLOT with the
# X-Internal-Secret header. The backend sends web pushes ONLY to users who
# explicitly enabled that slot in the panel settings (all defaults OFF,
# founder decision 2026-07-30) and is idempotent per user per local day, so a
# double-fired cron is a no-op.
#
# Railway: one cron service per slot, same repo. Two ways:
#   A) Settings → Start Command:  sh bin/railway-life-reminders-cron.sh
#   B) Settings → Builder: Dockerfile, path: Dockerfile.life-reminders-cron
# Cron Schedule (UTC — adjust to the founder's local offset):
#   morning    0 5 * * *          (05:00 UTC daily)
#   evening    0 19 * * *         (19:00 UTC daily)
#   weekly     0 17 * * 0         (17:00 UTC Sundays)
#   monthly    0 17 1 * *         (1st of each month)
#   quarterly  0 17 1 1,4,7,10 *  (1st of Jan/Apr/Jul/Oct)
#   yearly     0 17 1 1 *         (Jan 1st)
#   fiveyear   0 17 1 1 *         (Jan 1st; the backend no-ops off years when
#   tenyear    0 17 1 1 *          LIFE_REMINDER_ANCHOR_YEAR is set on the
#                                  web service — cron cannot say "every 5th
#                                  year", so the year gate lives server-side)
#
# Required variables:
#   LIFE_BACKEND_URL      public URL of the Flask app, e.g. https://dev.willpowerlab.com
#   LIFE_REMINDER_SECRET  must match the web service LIFE_REMINDER_SECRET
#   LIFE_REMINDER_SLOT    morning | evening | weekly | monthly | quarterly
#                         | yearly | fiveyear | tenyear

set -eu

BASE="${LIFE_BACKEND_URL%/}"
KEY="${LIFE_REMINDER_SECRET:-}"
SLOT="${LIFE_REMINDER_SLOT:-}"

if [ -z "$BASE" ] || [ -z "$KEY" ] || [ -z "$SLOT" ]; then
  echo "railway-life-reminders-cron: missing LIFE_BACKEND_URL, LIFE_REMINDER_SECRET or LIFE_REMINDER_SLOT"
  exit 1
fi

case "$SLOT" in
  morning|evening|weekly|monthly|quarterly|yearly|fiveyear|tenyear) ;;
  *)
    echo "railway-life-reminders-cron: LIFE_REMINDER_SLOT must be one of morning, evening, weekly, monthly, quarterly, yearly, fiveyear, tenyear (got: ${SLOT})"
    exit 1
    ;;
esac

echo "railway-life-reminders-cron: POST ${BASE}/v2/internal/life/reminders?slot=${SLOT}"

code="$(curl -sS -o /tmp/life_reminders_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/life/reminders?slot=${SLOT}" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${KEY}" \
  -d '{}')"

cat /tmp/life_reminders_body.txt
echo ""

if [ "$code" != "200" ]; then
  echo "railway-life-reminders-cron: HTTP ${code}"
  exit 1
fi

echo "railway-life-reminders-cron: ok"
exit 0
