#!/bin/sh
# One-shot job for Railway Cron: send the booking WhatsApp reminders that are
# due, then exit 0/1. Founder 2026-10-25 (N144): a reminder 1 hour before, on
# WhatsApp, to every booking that left a number on the booking form.
# Cloned from bin/railway-devbugs-cron.sh (the house HTTP-poker pattern).
#
# Fires POST /v2/internal/booking/whatsapp-reminders with the
# X-Internal-Secret header. The backend claims each booking before its
# message goes, so a double-fired cron sends nothing twice, and a booking is
# due from 1 hour before until 45 minutes before, so one missed run is fine.
#
# Railway: one cron service, same repo. Two ways:
#   A) Settings → Start Command:  sh bin/railway-booking-reminders-cron.sh
#   B) Settings → Builder: Dockerfile, path: Dockerfile.booking-reminders-cron
# Cron Schedule:  */5 * * * *   (every 5 minutes)
#
# Required variables:
#   BOOKING_BACKEND_URL      public URL of the Flask app
#   BOOKING_REMINDER_SECRET  must match the web service's BOOKING_REMINDER_SECRET

set -eu

BASE="${BOOKING_BACKEND_URL%/}"
SECRET="${BOOKING_REMINDER_SECRET:-}"

if [ -z "$BASE" ] || [ -z "$SECRET" ]; then
  echo "railway-booking-reminders-cron: missing BOOKING_BACKEND_URL or BOOKING_REMINDER_SECRET"
  exit 1
fi

echo "railway-booking-reminders-cron: POST ${BASE}/v2/internal/booking/whatsapp-reminders"

code="$(curl -sS -o /tmp/booking_reminders_body.txt -w "%{http_code}" -X POST \
  "${BASE}/v2/internal/booking/whatsapp-reminders" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: ${SECRET}" \
  -d '{}')"

cat /tmp/booking_reminders_body.txt
echo ""

if [ "$code" != "200" ]; then
  echo "railway-booking-reminders-cron: HTTP ${code}"
  exit 1
fi

echo "railway-booking-reminders-cron: ok"
exit 0
