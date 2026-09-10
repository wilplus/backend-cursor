#!/usr/bin/env bash
# Railway cron schedule: */5 * * * *
set -euo pipefail

: "${MLC3_GENERAL_SERVICE_EXPECTED_STATE:?missing expected rollout state}"

exec python scripts/monitor_mlc3_general_service.py \
  --expected-rollout-state "${MLC3_GENERAL_SERVICE_EXPECTED_STATE}" \
  --halt-on-hard-stop
