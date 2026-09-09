#!/usr/bin/env bash
# Railway cron schedule: */5 * * * *
set -euo pipefail

: "${MLC3_FOUNDER_CANARY_PRINCIPAL_ID:?missing exact founder principal}"
: "${MLC3_FOUNDER_CANARY_EXPECTED_STATE:?missing expected contract state}"

python scripts/monitor_mlc3_founder_canary.py \
  --principal-id "${MLC3_FOUNDER_CANARY_PRINCIPAL_ID}" \
  --expected-contract-state "${MLC3_FOUNDER_CANARY_EXPECTED_STATE}"
