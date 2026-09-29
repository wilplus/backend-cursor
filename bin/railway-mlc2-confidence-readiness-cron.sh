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
#   MLC2_CONFIDENCE_MONITORING_ENABLED=true
#
# The canary's "who" is the confidence_learning_writes ring row (0394), read
# from the database; no principal variable is needed since 2026-09-29.
#
# The check is read-only, sends only aggregate blocker evidence to Sentry and
# exits non-zero whenever any readiness invariant is unsafe. It cannot activate
# the producer; the cutover mode remains hard-coded dark in config.py.

set -eu

exec python scripts/check_mlc2_confidence_canary_readiness.py --json --alert
