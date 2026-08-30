#!/usr/bin/env bash
set -euo pipefail

: "${MLC3_REHEARSAL_DATABASE_URL:?Set this to a disposable PostgreSQL database}"

repo_dir="$(cd "$(dirname "$0")/../.." && pwd)"
prerequisites="$repo_dir/tests/integration/mlc3_exercise_foundation_prerequisites.sql"
migration="$repo_dir/migrations/add_mlc3_exercise_dark_foundation.sql"
rehearsal="$repo_dir/tests/integration/mlc3_exercise_foundation_rehearsal.sql"

psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$prerequisites"
psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"

# Reuse the full rejection rehearsal as committed disposable fixture setup.
# The normal rehearsal rolls back; only this isolated database commits it.
sed '$s/^ROLLBACK;$/COMMIT;/' "$rehearsal" \
  | psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 >/dev/null

register_sql="
SET ROLE service_role;
SELECT id FROM public.register_exercise_blind_packet_v1(
    'b2000000-0000-0000-0000-000000000006',
    'b0000000-0000-0000-0000-000000000004',
    (SELECT id FROM public.exercise_audio_lineages LIMIT 1),
    (SELECT id FROM public.exercise_authorization_checks
      WHERE idempotency_key = 'blind-review-auth-allowed'),
    '10000000-0000-0000-0000-000000000002',
    'confidence-exercise-blind-packet-v1',
    'confidence-five-state-v1',
    'b4000000-0000-0000-0000-000000000006',
    '2099-01-01T00:00:00Z', 2400, 'en', 'Measured passage.',
    'blind-policy-v1', 'concurrent-blind-packet'
);"

psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc "$register_sql" \
  >/dev/null &
first_pid=$!
psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc "$register_sql" \
  >/dev/null &
second_pid=$!
wait "$first_pid"
wait "$second_pid"

packet_count="$(psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM public.exercise_blind_packets WHERE idempotency_key = 'concurrent-blind-packet'")"
created_event_count="$(psql "$MLC3_REHEARSAL_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc \
  "SELECT count(*) FROM public.exercise_blind_packet_events WHERE idempotency_key = 'concurrent-blind-packet:created'")"

if [[ "$packet_count" != "1" || "$created_event_count" != "1" ]]; then
  echo "Concurrent idempotency rehearsal failed: packets=$packet_count events=$created_event_count" >&2
  exit 1
fi

echo "Concurrent blind-packet idempotency rehearsal passed."
