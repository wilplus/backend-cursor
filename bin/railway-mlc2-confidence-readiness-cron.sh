#!/bin/sh
# One-shot aggregate-only MLC-2 Confidence readiness monitor for Railway Cron.
#
# Railway service (same repository):
#   Builder:       Railpack
#   Start command: sh bin/railway-mlc2-confidence-readiness-cron.sh
#   Schedule:      */5 * * * *
#
# Required variables:
#   DATABASE_URL
#   SENTRY_DSN
#   DATA_FOUNDATION_CANARY_ENABLED=true
#   MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID=<verified founder principal UUID>
#   MLC2_CONFIDENCE_MONITORING_ENABLED=true
#
# The check is read-only, sends only aggregate blocker evidence to Sentry and
# exits non-zero whenever any readiness invariant is unsafe. It cannot activate
# the producer; the cutover mode remains hard-coded dark in config.py.

set -eu

exec python scripts/check_mlc2_confidence_canary_readiness.py --json --alert
