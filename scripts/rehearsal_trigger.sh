#!/usr/bin/env bash
#
# rehearsal_trigger.sh — does this change REQUIRE the PostgreSQL rehearsal tier?
#
# Exit 0 when the diff against the base branch touches a migration or an MLC-3
# storage path; exit 1 otherwise. Used by scripts/local_ci.sh and by the
# `checks` job in .github/workflows/tests.yml, so both agree on the trigger.
# The trigger is bound to the CHANGE, never to whether someone remembered
# (audit Q-T2, founder 2026-09-14).
#
#   scripts/rehearsal_trigger.sh          print the matching paths, exit 0/1
#   scripts/rehearsal_trigger.sh --quiet  exit code only
#   scripts/rehearsal_trigger.sh --why    one line naming what triggered it
#
# Base: origin/main (fetched shallowly if absent, as in a CI checkout). A diff
# that cannot be computed at all is treated as TRIGGERED: when in doubt, run
# the tier rather than silently skip it.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

MODE="${1:-}"

# The paths whose change means "rehearse before you call this green".
TRIGGER_PATHS=(
  'migrations/'
  'tests/integration/'
  'scripts/rehearsal_tier.sh'
  'services/first_client_repository.py'
  'services/mlc3_pilot_storage.py'
  'services/confident_moment_bundle_repository.py'
  'services/confident_moment_bundle.py'
  'services/confident_moment_delivery_worker.py'
  'services/confident_moment_user_media.py'
  'services/data_purge.py'
  'services/data_purge_registry.py'
  'services/rooting_coverage.py'
  'services/rooting_phrase.py'
  'services/rooting_phrase_qualification_v1.py'
  'services/mlc3_first_client_feedback.py'
  'services/mlc3_founder_canary_readiness.py'
  'services/mlc3_general_service_readiness.py'
  'services/user_media_storage.py'
  'services/coach_video_storage.py'
  'services/lab_audio_storage.py'
)

if ! git rev-parse --verify -q origin/main >/dev/null; then
  git fetch -q --depth=1 origin main >/dev/null 2>&1 || true
fi
if ! git rev-parse --verify -q origin/main >/dev/null; then
  [ "$MODE" = "--why" ] && echo "base branch unavailable; rehearsing to be safe"
  exit 0
fi
BASE="$(git merge-base origin/main HEAD 2>/dev/null || echo origin/main)"
CHANGED="$(git diff --name-only "$BASE" HEAD -- "${TRIGGER_PATHS[@]}" 2>/dev/null; git diff --name-only HEAD -- "${TRIGGER_PATHS[@]}" 2>/dev/null)"
CHANGED="$(printf '%s\n' "$CHANGED" | sed '/^$/d' | sort -u)"

if [ -z "$CHANGED" ]; then
  [ "$MODE" = "--why" ] && echo "no migration or MLC-3 storage change"
  exit 1
fi
case "$MODE" in
  --quiet) ;;
  --why)   echo "changed: $(printf '%s' "$CHANGED" | tr '\n' ' ')" ;;
  *)       printf '%s\n' "$CHANGED" ;;
esac
exit 0
